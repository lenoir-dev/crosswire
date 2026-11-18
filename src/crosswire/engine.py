import itertools
from dataclasses import dataclass, replace
from pathlib import Path
from . import git
from .cache import SummaryCache
from .findings import consolidate
from .diagnostics import hint, migration_hint, finding_limitations
from .integrate import integrate
from .coverage import inspect
from .model import BranchSummary, Report
from .rules import cw001, cw002, cw003, cw005
from .lang import adapters_for
from .lang.base import ADAPTER_API_VERSION, NamespaceId, Scope, Snapshot, Span, SymbolId, Use


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
        """Compatibility hook; definition comparison is adapter-owned."""
        adapter = self.analysis.adapters['python']
        symbol = side.definitions[module][name]
        parsed = adapter.parse(side.tip, symbol.path, module, side.roots)
        return parsed[2].get(name) if parsed is not None else None

    def definitions_equal(self, left, right, identity):
        adapter = self.analysis.adapters[identity.namespace.language]
        old = self.analysis.semantic(left, adapter.name).definitions[identity]
        new = self.analysis.semantic(right, adapter.name).definitions[identity]
        snap = self.analysis.snapshot(left.tip, left.roots)
        return adapter.definitions_equal(snap, old,
            self.analysis.snapshot(right.tip, right.roots), new, adapter.context(snap))


class AdapterIndex:
    """Caller-aware resolution facade with run-scoped adapter context."""

    def __init__(self, adapter, snapshot, context):
        self.adapter = adapter
        self.snapshot = snapshot
        self.context = context
        self.repo, self.commit = snapshot.repo, snapshot.commit

    def resolve_use(self, ref):
        if not isinstance(ref, Use):
            namespaces = self.adapter.namespaces_of(ref.path, self.context)
            caller = NamespaceId(self.adapter.name, namespaces[0]) if namespaces else None
            ref = Use(SymbolId(NamespaceId(self.adapter.name, ref.module), ref.name),
                      Span(ref.path, ref.line), ref.call, caller)
        return self.adapter.resolve(self.snapshot, ref, self.context)

    def resolve(self, module, name):
        return self.resolve_use(Use(SymbolId(NamespaceId(self.adapter.name, module), name), Span('', 0)))


class _Analysis:
    def __init__(self, repo):
        self.repo = repo
        self.adapters = adapters_for(repo)
        self.contexts = {}
        self.indexes = {}
        self.changed_paths = set()
        self.changed = {}
        self.consulted = {}
        self.observed = {}
        self.candidates = {}
        self.invariants = {}

    @property
    def parse_failures(self):
        return sum(adapter.parse_failures for adapter in self.adapters.values())

    def snapshot(self, sha, roots, *, track=True):
        return Snapshot(self.repo, sha, tuple(roots), track)

    def context(self, sha, roots, language='python'):
        adapter = self.adapters[language]
        key = (sha, tuple(roots), ADAPTER_API_VERSION, language, adapter.version)
        if key not in self.contexts:
            self.contexts[key] = adapter.context(self.snapshot(sha, roots))
        return self.contexts[key]

    def semantic(self, summary, language='python'):
        return next(item for item in summary.semantics if item.language == language)

    def roots_for(self, sha, configured=None):
        # --src and the legacy source-root heuristic belong to Python (P2).
        return self.adapters['python'].source_roots(self.snapshot(sha, ('.',)), configured)

    def index(self, sha, roots, *, track=True, language='python'):
        adapter = self.adapters[language]
        ctx = self.context(sha, roots, language)
        snap = self.snapshot(sha, roots, track=track)
        key = (sha, adapter.cache_identity(ctx), track)
        if key not in self.indexes:
            consulted = self.consulted.setdefault((sha, tuple(roots)), set()) if track else None
            adapter.index(snap, ctx, consulted)
            self.indexes[key] = AdapterIndex(adapter, snap, ctx)
        return self.indexes[key]

    def namespaces(self, sha, path, roots, language='python'):
        adapter = self.adapters[language]
        return tuple(NamespaceId(language, name) for name in
                     adapter.namespaces_of(path, self.context(sha, roots, language)))

    def violations(self, sha, roots, paths):
        """Evaluate state invariants independently of branch deltas and trials."""
        found = []
        for name, adapter in self.adapters.items():
            ctx = self.context(sha, roots, name)
            scope = Scope(tuple(sorted(set(paths))), ctx)
            key = (sha, adapter.cache_identity(ctx), scope.paths)
            if key not in self.invariants:
                self.invariants[key] = tuple(adapter.violations(self.snapshot(sha, roots), scope))
            found.extend(self.invariants[key])
        return found

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
        return self.adapters['python'].warn_parse(path, sha)

    def parse(self, sha, path, module, roots):
        """Retained 0.4 hook; parsing is implemented by the Python adapter."""
        return self.adapters['python'].parse(sha, path, module, roots)

    def references(self, sha, path, module, *, quiet=False, roots=('.',)):
        """Retained reference hook used by target-candidate discovery."""
        return self.adapters['python'].references(sha, path, module, quiet=quiet, roots=roots)

    def side(self, label, sha, base, roots):
        changes = git.changed_files(self.repo, base, sha)
        # Register tracked state before the adapter resolves replacement bindings.
        self.index(sha, roots)
        for name in self.adapters:
            self.context(base, roots, name)
        paths = {path for change in changes for path in (change.path, change.old_path) if path}
        self.violations(base, roots, paths)
        self.violations(sha, roots, paths)
        summaries = tuple(adapter.summarize(self.snapshot(base, roots), self.snapshot(sha, roots),
                          changes, self.context(sha, roots, name))
                          for name, adapter in self.adapters.items())
        return replace(summaries[0].legacy, label=label, semantics=summaries)


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
    disk_cache = SummaryCache(git.common_dir(repo), analysis.adapters, repo) if cache else None
    pairs, findings = {}, []
    summaries = {}
    roots_by_base = {}
    parents = git.direct_parents(repo, shas) if base_sha is None else {}
    bases = git.pair_bases(repo, shas)
    merges = git.pair_merges(repo, shas) if textual else None
    for (a, asha), (b, bsha) in itertools.combinations(zip(branches, shas), 2):
        a_parents = parents.get(asha, ())
        b_parents = parents.get(bsha, ())
        if base_sha:
            common = base_sha
        elif len(a_parents) == len(b_parents) == 1 and a_parents == b_parents:
            common = a_parents[0]
        else:
            common = bases.unique(asha, bsha)
            if common is None:
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
                    roots_by_base[branch_base] = analysis.roots_for(branch_base)
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
        conflicts = merges.conflicts(asha, bsha) if textual else []
        ctx = PairContext(
            repo,
            common,
            left,
            right,
            textual,
            conflicts,
            analysis)
        if interacts(left, right):
            for rule in (cw001, cw002, cw003):
                findings.extend(rule.check(ctx))
            for adapter in analysis.adapters.values():
                results = adapter.pairwise_rules(ctx)
                if results:
                    merged = integrate(repo, asha, [(b, bsha)])
                    if not merged.skipped:
                        results = [replace(f, hint=hint(f) or adapter.state_hint(
                            analysis.snapshot(merged.commit, left.roots), f)) for f in results]
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
    """Compare language-qualified namespaces and adapter rule payloads."""
    for a in left.semantics:
        for b in right.semantics:
            if a.language != b.language:
                continue
            if (a.touched_namespaces & b.referenced_namespaces
                    or b.touched_namespaces & a.referenced_namespaces
                    or {key.namespace for key in a.definitions} & {key.namespace for key in b.definitions}
                    or (a.rule_data and b.rule_data)):
                return True
    return False
