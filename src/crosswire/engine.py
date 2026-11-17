import hashlib
import itertools
import sys
from dataclasses import dataclass
from pathlib import Path
from . import git
from .diffing import added_references, api_changes
from .python_analyzer import module_name_for_path, extract_symbols, extract_references, definition_dumps
from .model import Report
from .rules import cw001, cw002, cw003, cw004, cw005

@dataclass
class Side:
    label: str
    sha: str
    changes: list
    api: dict
    references: list
    definitions: dict
    dumps: dict
    modules: dict
    redefined: set
    migrations: dict

@dataclass
class PairContext:
    repo: Path
    base: str
    a: Side
    b: Side
    textual: bool
    conflicts: list

class _Analysis:
    def __init__(self, repo):
        self.repo = repo
        self.cache = {}
        self.warned = set()
    def parse(self, sha, path, module, roots):
        source = git.read_file(self.repo, sha, path)
        if source is None: return {}, [], {}
        key = (hashlib.sha256(source.encode()).digest(), module, path, tuple(roots))
        if key not in self.cache:
            try:
                self.cache[key] = (extract_symbols(source, module, path), extract_references(source, module, path, path.endswith('/__init__.py') or path == '__init__.py'), definition_dumps(source))
            except SyntaxError:
                self.cache[key] = None
        value = self.cache[key]
        if value is None:
            if (path, sha) not in self.warned:
                print(f'crosswire: warning: cannot parse {path}@{sha[:7]}', file=sys.stderr)
                self.warned.add((path, sha))
            return None
        return value
    def side(self, label, sha, base, roots, base_files):
        changes = git.changed_files(self.repo, base, sha)
        api, refs, defs, dumps, modules, migrations, redefined = {}, [], {}, {}, {}, {}, set()
        for c in changes:
            oldpath = c.old_path if c.status == 'R' else c.path
            oldmod = module_name_for_path(oldpath, roots)
            newmod = module_name_for_path(c.path, roots)
            old_result = self.parse(base, oldpath, oldmod, roots) if oldmod and c.status != 'A' else ({}, [], {})
            new_result = self.parse(sha, c.path, newmod, roots) if newmod and c.status != 'D' else ({}, [], {})
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
                    redefined.update((newmod, name) for name in newsyms if name not in oldsyms or olddumps.get(name) != newdumps.get(name))
                if c.status not in ('D', 'R'):
                    api.setdefault(newmod, []).extend(api_changes(oldsyms, newsyms))
                if c.status == 'R':
                    # Compare occurrences across a rename using the new path.
                    from dataclasses import replace
                    oldrefs = [replace(r, path=c.path) for r in renamed_refs]
                refs.extend(added_references(oldrefs, newrefs))
                additions = {k: v for k, v in newsyms.items() if k not in oldsyms}
                if additions: defs.setdefault(newmod, {}).update(additions)
                dumps[newmod] = newdumps
            if c.status == 'A' and c.path.endswith('.py'):
                source = git.read_file(self.repo, sha, c.path)
                if source is not None: migrations[c.path] = source
        return Side(label, sha, changes, api, refs, defs, dumps, modules, redefined, migrations)

def analyze(repo, branches, base=None, src=None, textual=True):
    repo = git.repo_root(repo)
    git.git_version(repo)
    if len(branches) < 2: raise git.GitError('at least two branches are required')
    shas = [git.resolve(repo, b) for b in branches]
    if len(set(shas)) != len(shas): raise git.GitError('branches must resolve to distinct commits')
    base_sha = git.resolve(repo, base) if base is not None else None
    analysis = _Analysis(repo)
    pairs, findings = {}, []
    for (a, asha), (b, bsha) in itertools.combinations(zip(branches, shas), 2):
        common = base_sha or git.merge_base(repo, asha, bsha)
        if common is None: raise git.GitError(f'no merge base for {a} and {b}')
        if base_sha and (not git.is_ancestor(repo, common, asha) or not git.is_ancestor(repo, common, bsha)):
            raise git.GitError(f'base is not an ancestor of both {a} and {b}')
        pairs[(a, b)] = common
        files = git.list_files(repo, common)
        roots = src if src is not None else (['src', '.'] if any(p.startswith('src/') for p in files) else ['.'])
        left = analysis.side(a, asha, common, roots, files)
        right = analysis.side(b, bsha, common, roots, files)
        conflicts = git.merge_tree_conflicts(repo, asha, bsha) if textual else []
        ctx = PairContext(repo, common, left, right, textual, conflicts)
        for rule in (cw001, cw002, cw003, cw004, cw005): findings.extend(rule.check(ctx))
    unique = {}
    for f in findings:
        key = (f.rule, f.branch, f.other_branch, f.path, f.line, f.symbol)
        unique.setdefault(key, f)
    ordered = sorted(unique.values(), key=lambda f: (f.path, f.line, f.rule, f.branch, f.other_branch, f.symbol or '', f.message))
    return Report(pairs, ordered)
