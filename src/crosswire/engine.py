import hashlib
import itertools
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from . import git
from .cache import SummaryCache
from .diffing import added_references, api_changes
from .python_analyzer import module_name_for_path, extract_symbols, extract_references, definition_dumps
from .model import BranchSummary, Report
from .rules import cw001, cw002, cw003, cw004, cw005


@dataclass
class PairContext:
    repo: Path
    base: str
    a: BranchSummary
    b: BranchSummary
    textual: bool
    conflicts: list
    analysis: object

    def definition_dump(self, side, module, name):
        """Return a normalized AST for a definition at a branch tip."""
        symbol = side.definitions[module][name]
        parsed = self.analysis.parse(side.tip, symbol.path, module, side.roots)
        return parsed[2].get(name) if parsed is not None else None


class _Analysis:
    def __init__(self, repo):
        self.repo = repo
        self.cache = {}
        self.warned = set()
        self.parse_failures = 0

    def parse(self, sha, path, module, roots):
        """Parse."""
        source = git.read_file(self.repo, sha, path)
        if source is None:
            return {}, [], {}
        key = (
            hashlib.sha256(
                source.encode()).digest(),
            module,
            path,
            tuple(roots))
        if key not in self.cache:
            try:
                self.cache[key] = (
                    extract_symbols(
                        source,
                        module,
                        path),
                    extract_references(
                        source,
                        module,
                        path,
                        path.endswith('/__init__.py') or path == '__init__.py'),
                    definition_dumps(source))
            except SyntaxError:
                self.cache[key] = None
        value = self.cache[key]
        if value is None:
            self.parse_failures += 1
            if (path, sha) not in self.warned:
                print(
                    f'crosswire: warning: cannot parse {path}@{sha[:7]}',
                    file=sys.stderr)
                self.warned.add((path, sha))
            return None
        return value

    def side(self, label, sha, base, roots):
        """Side."""
        changes = git.changed_files(self.repo, base, sha)
        api, refs, defs, dumps, modules, migrations, redefined = {}, [], {}, {}, {}, {}, set()
        for c in changes:
            oldpath = c.old_path if c.status == 'R' else c.path
            oldmod = module_name_for_path(oldpath, roots)
            newmod = module_name_for_path(c.path, roots)
            old_result = self.parse(
                base,
                oldpath,
                oldmod,
                roots) if oldmod and c.status != 'A' else (
                {},
                [],
                {})
            new_result = self.parse(
                sha,
                c.path,
                newmod,
                roots) if newmod and c.status != 'D' else (
                {},
                [],
                {})
            if old_result is None or new_result is None:
                continue
            oldsyms, oldrefs, olddumps = old_result
            newsyms, newrefs, newdumps = new_result
            renamed_refs = oldrefs
            if oldmod and (c.status in ('D', 'R') or oldmod != newmod):
                api.setdefault(oldmod, []).extend(api_changes(oldsyms, {}))
                oldsyms, oldrefs = {}, []
            if newmod:
                if c.status != 'D':
                    modules[newmod] = newsyms
                    redefined.update((newmod, name) for name in newsyms if name not in oldsyms or olddumps.get(
                        name) != newdumps.get(name))
                if c.status not in ('D', 'R'):
                    api.setdefault(
                        newmod, []).extend(
                        api_changes(
                            oldsyms, newsyms))
                if c.status == 'R':
                    # Compare occurrences across a rename using the new path.
                    oldrefs = [replace(r, path=c.path) for r in renamed_refs]
                refs.extend(added_references(oldrefs, newrefs))
                additions = {k: v for k,
                             v in newsyms.items() if k not in oldsyms}
                if additions:
                    defs.setdefault(newmod, {}).update(additions)
                dumps[newmod] = newdumps
            if c.status == 'A' and c.path.endswith('.py'):
                source = git.read_file(self.repo, sha, c.path)
                if source is not None:
                    migrations[c.path] = source
        return BranchSummary(
            label, sha, base, tuple(roots), tuple(changes),
            {module: tuple(items)
             for module, items in api.items()}, tuple(refs),
            defs, frozenset(redefined), migrations,
            frozenset(module for module, items in api.items() if items),
            frozenset(ref.module for ref in refs),
        )


def summarize(repo, label, tip, base, roots):
    """Summarize a branch relative to a resolved base commit."""
    return _Analysis(repo).side(label, tip, base, roots)


def analyze(repo, branches, base=None, src=None, textual=True, target=None, cache=True):
    """Compare each pair of branches and return a deterministic report."""
    repo = git.repo_root(repo)
    git.git_version(repo)
    if len(branches) < 2:
        raise git.GitError('at least two branches are required')
    shas = [git.resolve(repo, b) for b in branches]
    if len(set(shas)) != len(shas):
        raise git.GitError('branches must resolve to distinct commits')
    if base is not None and target is not None:
        raise git.GitError('--base and --target are mutually exclusive')
    base_sha = git.resolve(repo, base) if base is not None else None
    target_sha = git.resolve(repo, target) if target is not None else None
    target_bases = {}
    if target_sha:
        for label, sha in zip(branches, shas):
            target_bases[sha] = git.merge_base(repo, sha, target_sha)
            if target_bases[sha] is None:
                raise git.GitError(f'no merge base for {label} and {target}')
    analysis = _Analysis(repo)
    disk_cache = SummaryCache(git.common_dir(repo)) if cache else None
    pairs, findings = {}, []
    summaries = {}
    roots_by_base = {}
    for (a, asha), (b, bsha) in itertools.combinations(zip(branches, shas), 2):
        common = base_sha or git.merge_base(repo, asha, bsha)
        if common is None:
            raise git.GitError(f'no merge base for {a} and {b}')
        if base_sha and (not git.is_ancestor(repo, common, asha)
                         or not git.is_ancestor(repo, common, bsha)):
            raise git.GitError(f'base is not an ancestor of both {a} and {b}')
        pairs[(a, b)] = common
        def get_summary(label, tip):
            branch_base = target_bases[tip] if target_sha else common
            if src is None:
                if branch_base not in roots_by_base:
                    files = git.list_files(repo, branch_base)
                    roots_by_base[branch_base] = (
                        ('src', '.') if any(p.startswith('src/') for p in files) else ('.',)
                    )
                roots = roots_by_base[branch_base]
            else:
                roots = tuple(src)
            key = (tip, branch_base, roots)
            if key not in summaries:
                summary = disk_cache.get(label, branch_base, tip, roots) if disk_cache else None
                if summary is None:
                    failures_before = analysis.parse_failures
                    summary = analysis.side(label, tip, branch_base, roots)
                    if disk_cache and analysis.parse_failures == failures_before:
                        disk_cache.put(summary)
                summaries[key] = summary
            return summaries[key]

        left = get_summary(a, asha)
        right = get_summary(b, bsha)
        conflicts = git.merge_tree_conflicts(
            repo, asha, bsha) if textual else []
        ctx = PairContext(
            repo,
            common,
            left,
            right,
            textual,
            conflicts,
            analysis)
        interacts = (
            left.touched_modules & right.referenced_modules
            or right.touched_modules & left.referenced_modules
            or left.definitions.keys() & right.definitions.keys()
            or (left.migrations and right.migrations)
        )
        if interacts:
            for rule in (cw001, cw002, cw003, cw004):
                findings.extend(rule.check(ctx))
        findings.extend(cw005.check(ctx))
    unique = {}
    for f in findings:
        key = (f.rule, f.branch, f.other_branch, f.path, f.line, f.symbol)
        unique.setdefault(key, f)
    ordered = sorted(
        unique.values(),
        key=lambda f: (
            f.path,
            f.line,
            f.rule,
            f.branch,
            f.other_branch,
            f.symbol or '',
            f.message))
    return Report(pairs, ordered)
