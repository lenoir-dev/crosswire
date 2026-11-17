from .parsing import PARSE_ERRORS
import hashlib
import itertools
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from . import git
from .cache import SummaryCache
from .findings import consolidate
from .diagnostics import hint, migration_hint, finding_limitations
from .integrate import integrate
from .coverage import inspect
from .diffing import added_references, api_changes
from .python_analyzer import module_name_for_path, extract_symbols, cached_references, definition_dumps
from .model import BranchSummary, Report
from .rules import cw001, cw002, cw003, cw004, cw005
from .state import StateIndex


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
        self.module_cache = {}
        self.indexes = {}
        self.changed_paths = set()
        self.changed = {}
        self.consulted = {}
        self.observed = {}
        self.candidates = {}

    def index(self, sha, roots, *, track=True):
        """Share state indexes and a run-sized blob cache without LRU eviction."""
        key = (sha, tuple(roots))
        if not track:
            return StateIndex(self.repo, sha, roots, self.module_cache)
        if key not in self.indexes:
            consulted = self.consulted.setdefault(key, set())
            self.indexes[key] = StateIndex(self.repo, sha, roots, self.module_cache, consulted)
        return self.indexes[key]

    def observe(self, sha, roots, ref):
        """Record a user-state reference evaluated by the semantic analysis."""
        self.observed.setdefault((sha, tuple(roots)), set()).add(ref)

    def track_summary(self, summary):
        """Restore coverage scope even when a summary came from disk cache."""
        paths = self.changed.setdefault((summary.tip, summary.roots), set())
        for change in summary.changes:
            paths.add(change.path)
            self.changed_paths.add(change.path)
            if change.old_path:
                paths.add(change.old_path)
                self.changed_paths.add(change.old_path)
        for ref in summary.references:
            self.observe(summary.tip, summary.roots, ref)

    def track_state(self, sha, summaries):
        """Include changed files in a requested integrated state, never trial states."""
        for summary in summaries:
            paths = self.changed.setdefault((sha, summary.roots), set())
            for change in summary.changes:
                paths.add(change.path)
                if change.old_path:
                    paths.add(change.old_path)

    def warn_parse(self, path, sha):
        """Warn once for a file in a revision, shared with coverage collection."""
        entry = git.tree_entries(str(self.repo), sha).get(path)
        identity = (path, entry[1] if entry else sha)
        if identity not in self.warned:
            print(f'crosswire: warning: cannot parse {path}@{sha[:7]}', file=sys.stderr)
            self.warned.add(identity)

    def parse(self, sha, path, module, roots):
        """Parse."""
        try:
            source = git.read_file(self.repo, sha, path)
        except git.SkippedBlob:
            self.parse_failures += 1
            return None
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
                    cached_references(
                        source,
                        module,
                        path,
                        path.endswith('/__init__.py') or path == '__init__.py'),
                    definition_dumps(source))
            except PARSE_ERRORS:
                self.cache[key] = None
        value = self.cache[key]
        if value is None:
            self.parse_failures += 1
            self.warn_parse(path, sha)
            return None
        return value

    def references(self, sha, path, module, *, quiet=False):
        """Get cached references without extracting symbols or AST dumps."""
        try:
            source = git.read_file(self.repo, sha, path)
        except git.SkippedBlob:
            self.parse_failures += 1
            return None
        if source is None:
            return ()
        try:
            return cached_references(source, module, path,
                                     path.endswith('/__init__.py') or path == '__init__.py')
        except PARSE_ERRORS:
            self.parse_failures += 1
            if not quiet:
                self.warn_parse(path, sha)
            return None

    def side(self, label, sha, base, roots):
        """Side."""
        changes = git.changed_files(self.repo, base, sha)
        tip_index = self.index(sha, roots)
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
                replacement = tip_index._module(oldmod)
                replacement_result = self.parse(sha, replacement[0], oldmod, roots) if replacement else ({}, [], {})
                if replacement_result is not None:
                    api.setdefault(oldmod, []).extend(api_changes(oldsyms, replacement_result[0]))
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
            if c.status == 'A' and c.path.endswith('.py') and (cw004._DJANGO.match(c.path) or 'versions' in c.path.split('/')[:-1]):
                try:
                    source = git.read_file(self.repo, sha, c.path)
                except git.SkippedBlob:
                    source = None
                if source is not None:
                    migrations[c.path] = source
        api = {module: [change for change in items
                        if change.kind != 'removed' or (not tip_index.is_open(module)
                            and tip_index.resolve(module, change.qualname).status != 'valid')]
               for module, items in api.items()}
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
    parents = git.direct_parents(repo, shas) if base_sha is None else {}
    for (a, asha), (b, bsha) in itertools.combinations(zip(branches, shas), 2):
        a_parents = parents.get(asha, ())
        b_parents = parents.get(bsha, ())
        if base_sha:
            common = base_sha
        elif len(a_parents) == len(b_parents) == 1 and a_parents == b_parents:
            common = a_parents[0]
        else:
            common = git.merge_base(repo, asha, bsha)
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
                analysis.track_summary(summary)
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
        if interacts(left, right):
            for rule in (cw001, cw002, cw003, cw004):
                results = rule.check(ctx)
                if rule is cw004 and results:
                    merged = integrate(repo, asha, [(b, bsha)])
                    if not merged.skipped:
                        results = [replace(f, hint=hint(f) or migration_hint(repo, merged.commit, f)) for f in results]
                findings.extend(results)
        findings.extend(cw005.check(ctx))
    ordered = sorted(
        (replace(f, hint=f.hint or hint(f), limitations=finding_limitations(f))
         for f in consolidate(findings)),
        key=lambda f: (
            f.path,
            f.line,
            f.rule,
            f.branch,
            f.other_branch,
            f.symbol or '',
            f.message))
    limitations = inspect(repo, shas, src, analysis)
    return Report(pairs, ordered, 'partial' if limitations else 'complete', limitations)


def interacts(left, right):
    """Return whether two branch summaries can interact semantically."""
    return bool(left.touched_modules & right.referenced_modules
                or right.touched_modules & left.referenced_modules
                or left.definitions.keys() & right.definitions.keys()
                or (left.migrations and right.migrations))
