"""Analyze the integrated state of an ordered set of branches."""

import itertools
from dataclasses import dataclass, replace
from collections import Counter

from . import git
from .cache import SummaryCache
from .engine import PairContext, _Analysis, interacts
from .findings import consolidate
from .diagnostics import hint, reproduction, migration_hint, finding_limitations
from .coverage import inspect
from .integrate import integrate
from .rules import cw001, cw002, cw003
from .lang.base import NamespaceId, Reason, Verdict


@dataclass(frozen=True, slots=True)
class CombinedFinding:
    """A finding attributed to a set of integrated branches."""

    rule: str
    severity: str
    message: str
    branch: str
    culprits: tuple[str, ...]
    culprits_exact: bool
    resolved_by: tuple[str, ...] | None
    path: str
    line: int
    location: str
    symbol: str | None
    hint: str | None = None
    limitations: tuple[str, ...] = ()
    repro: str | None = None


@dataclass(frozen=True, slots=True)
class CombinedReport:
    """Combined-mode result, separate from the stable pairwise report."""

    target: str
    integrated: tuple[str, ...]
    skipped: tuple[tuple[str, tuple[str, ...]], ...]
    findings: list[CombinedFinding]
    coverage: str = 'complete'
    limits: dict | None = None
    commit: str | None = None
    limitations: dict | None = None


def _broken(ref, tip, final, final_index):
    verdict = final_index.adapter.breakage(ref, tip, final,
                                          final_index.snapshot, final_index.context)
    return verdict.detail if verdict.status == 'broken' else None


def _invalid_call(ref, resolution, index):
    return (ref.call is not None and index.adapter.check_call(
        ref, resolution.binding, resolution.binding).reason == Reason.INVALID_BASELINE)


def _call_hint(reason, resolution, index):
    return index.adapter.call_hint(Verdict('broken', Reason.INCOMPATIBLE_CALL, reason), resolution.binding)


def _location(repo, commit, ref, roots, analysis):
    adapter = analysis.adapters[ref.language]
    return adapter.locate(analysis.snapshot(commit, roots), ref,
                          analysis.context(commit, roots, adapter.name))


def _changed_paths(summary):
    paths = set()
    for item in summary.changes:
        paths.add(item.path)
        if item.old_path:
            paths.add(item.old_path)
    return paths


def _subsets(candidates):
    labels = sorted(candidates)
    for size in range(1, min(3, len(labels)) + 1):
        yield from itertools.combinations(labels, size)


class AnalysisRun:
    """Immutable input setup and shared analysis caches for a single CLI run."""

    def __init__(self, repo, branches, target, src=None, cache=True):
        repo = git.repo_root(repo)
        git.git_version(repo)
        if not target:
            raise git.GitError('--combined requires --target')
        target_sha = git.resolve(repo, target)
        shas = [git.resolve(repo, b) for b in branches]
        if len(set(shas)) != len(shas):
            raise git.GitError('branches must resolve to distinct commits')
        ordered = list(zip(branches, shas))
        analysis = _Analysis(repo)
        disk = SummaryCache(git.common_dir(repo), analysis.adapters, repo) if cache else None
        summaries = {}
        for label, sha in ordered:
            base = git.merge_base(repo, sha, target_sha)
            if base is None:
                raise git.GitError(f'no merge base for {label} and {target}')
            roots = analysis.roots_for(base, src)
            summary = disk.get(label, base, sha, roots) if disk else None
            if summary is None:
                failures = analysis.parse_failures
                summary = analysis.side(label, sha, base, roots)
                if disk and failures == analysis.parse_failures:
                    disk.put(summary)
            summaries[label] = summary
            analysis.track_summary(summary)
        self.repo = repo
        self.target = target
        self.target_sha = target_sha
        self.shas = dict(ordered)
        self.summaries = summaries
        self.analysis = analysis
        self.ancestors = git.ancestor_relations(repo, shas)
        self.roots = analysis.roots_for(target_sha, src)
        self._reverse = None

    def index(self, commit, roots):
        """Reuse one resolution index per state and source-root context."""
        return self.analysis.index(commit, roots)

    def target_candidates(self, changed_paths):
        """Select target callers by changed modules, including re-export chains."""
        if self._reverse is None:
            self._reverse = {}
            target_index = self.analysis.index(self.target_sha, self.roots, track=False)
            for path in git.list_files(self.repo, self.target_sha):
                namespaces = self.analysis.namespaces(self.target_sha, path, self.roots)
                if not namespaces:
                    continue
                refs = self.analysis.references(self.target_sha, path, namespaces[0].name, quiet=True, roots=self.roots)
                for ref in refs or ():
                    modules = {NamespaceId(ref.language, ref.module)}
                    modules.update(namespace for p in target_index.resolve_use(ref).files
                                   for namespace in self.analysis.namespaces(self.target_sha, p, self.roots))
                    for imported in modules:
                        self._reverse.setdefault(imported, set()).add(path)
        changed_modules = {namespace for path in changed_paths
                           for namespace in self.analysis.namespaces(self.target_sha, path, self.roots)}
        return sorted({path for module in changed_modules if module is not None
                       for path in self._reverse.get(module, ())})


def _rename_hint(finding, run, commit):
    """Use a unique removal/rename only when the replacement exists in this state."""
    if finding.rule != 'CW001' or finding.resolved_by is not None or not finding.culprits_exact:
        return None
    if len(finding.culprits) != 1:
        return None
    cause = run.summaries.get(finding.culprits[0])
    if cause is None:
        return None
    for data in cause.semantics:
        for change in data.api:
            module, name = change.identity.namespace.name, change.identity.name
            if (change.kind == 'removed' and change.rename_hint
                    and f'{module}.{name}' == finding.symbol
                    and run.index(commit, cause.roots).resolve(module, change.rename_hint).status == 'valid'):
                return f'use `{module}.{change.rename_hint}`'
    return None


def analyze_combined(repo, branches, target, src=None, cache=True, min_branches=1,
                     collect_coverage=True, _run=None, repro_repo=None):
    """Integrate branches and find new broken references in the final state."""
    if len(branches) < min_branches:
        raise git.GitError(f'at least {min_branches} branches are required')
    run = _run or AnalysisRun(repo, branches, target, src, cache)
    repo = run.repo
    target_sha = run.target_sha
    shas = [run.shas[label] for label in branches]
    ordered = list(zip(branches, shas))
    analysis = run.analysis
    summaries = run.summaries
    merged = integrate(repo, target_sha, ordered)
    invariant_paths = set().union(*(_changed_paths(summaries[label]) for label in branches))
    analysis.violations(target_sha, run.roots, invariant_paths)
    for label, sha in ordered:
        analysis.violations(sha, summaries[label].roots, invariant_paths)
    analysis.violations(merged.commit, run.roots, invariant_paths)
    integrated = set(merged.integrated)
    live = [(label, sha) for label, sha in ordered if label in integrated]
    index = run.index
    def trial(labels):
        selected = [(label, sha) for label, sha in live if label in labels]
        result = integrate(repo, target_sha, selected)
        if not result.skipped:
            analysis.violations(result.commit, run.roots, invariant_paths)
        return None if result.skipped else result.commit
    findings = []
    limits_hit = set()
    preceding = []
    skips = dict(merged.skipped)
    for label, sha in ordered:
        if label in skips:
            conflicts = set(skips[label])
            candidates = [other for other in preceding
                          if _changed_paths(summaries[other]) & conflicts]
            culprits = tuple(sorted(candidates))
            exact = False
            for subset in [(), *(_subsets(candidates) if len(candidates) <= 6 else ())]:
                subset_set = set(subset)
                prior = [(other, other_sha) for other, other_sha in ordered
                         if other in subset_set]
                attempt = integrate(repo, target_sha, prior + [(label, sha)])
                if not attempt.skipped:
                    analysis.violations(attempt.commit, run.roots, invariant_paths)
                if (label in dict(attempt.skipped)
                        and all(other in attempt.integrated for other in subset)):
                    culprits, exact = subset or (target,), True
                    break
            if not exact and len(candidates) > 3:
                limits_hit.add('max_candidates' if len(candidates) > 6 else 'max_group')
            for path in skips[label]:
                conflict_with = ', '.join(culprits) if culprits else target
                findings.append(CombinedFinding('CW005', 'error', f'textual conflict with {conflict_with}',
                                                label, culprits, exact, None,
                                                path, 1, 'branch', None))
        else:
            preceding.append(label)
    for label, sha in live:
        summary = summaries[label]
        roots = summary.roots
        tip_index = index(sha, roots)
        final_index = index(merged.commit, roots)
        for ref in analysis.semantic(summary).uses:
            analysis.observe(merged.commit, roots, ref)
            tip = tip_index.resolve_use(ref)
            if tip.status != 'valid':
                continue
            if _invalid_call(ref, tip, tip_index):
                continue
            final = final_index.resolve_use(ref)
            reason = _broken(ref, tip, final, final_index)
            location = _location(repo, merged.commit, ref, roots, analysis)
            if reason is None or location is None:
                continue
            relevant = set(tip.files) | set(final.files)
            candidates = [other for other, _ in live if other != label and _changed_paths(summaries[other]) & relevant]
            culprits = tuple(sorted(candidates))
            exact = False
            for subset in [(), *(_subsets(candidates) if len(candidates) <= 6 else ())]:
                commit = trial(set(subset) | {label})
                if commit is None:
                    continue
                trial_index = index(commit, roots)
                if _broken(ref, tip, trial_index.resolve_use(ref), trial_index) is not None:
                    culprits, exact = subset or (target,), True
                    break
            if not exact and len(candidates) > 3:
                limits_hit.add('max_candidates' if len(candidates) > 6 else 'max_group')
            symbol = f'{ref.module}.{ref.name}'
            if len(culprits) == 1:
                rule = 'CW001' if reason == 'undefined' else 'CW002'
                message = (f'`{symbol}` is used here but was removed in {culprits[0]}' if rule == 'CW001'
                           else f'`{symbol}` call is incompatible with {culprits[0]}: {reason}')
            else:
                rule = 'CW006'
                message = f'`{symbol}` is broken after merging {{{", ".join(culprits)}}}: {reason}; no single branch causes it'
            findings.append(CombinedFinding(rule, 'error', message, label, tuple(culprits), exact, None,
                                            ref.path, location[0], location[1], symbol,
                                            hint=(f'rebase {label} onto {target}' if culprits == (target,) else
                                                  _call_hint(reason, final, final_index) if rule == 'CW002' else None)))
    # Recheck occurrences already present on the target against the integrated state.
    roots = run.roots
    changed_paths = {path for change in git.changed_files(repo, target_sha, merged.commit)
                     for path in (change.path, change.old_path) if path}
    target_index = index(target_sha, roots)
    final_index = index(merged.commit, roots)
    candidates = run.target_candidates(changed_paths)
    analysis.candidates.setdefault((target_sha, roots), set()).update(candidates)
    analysis.candidates.setdefault((merged.commit, roots), set()).update(candidates)
    for path in candidates:
        module = analysis.namespaces(target_sha, path, roots)[0].name
        old = analysis.references(target_sha, path, module, roots=roots)
        new = analysis.references(merged.commit, path, module, roots=roots)
        if old is None or new is None:
            continue
        def ref_key(ref):
            return ref.language, ref.path, ref.module, ref.name, ref.call
        remaining = Counter(ref_key(ref) for ref in old)
        for ref in sorted(new, key=lambda item: item.line):
            key = ref_key(ref)
            if not remaining[key]:
                continue
            remaining[key] -= 1
            analysis.observe(target_sha, roots, ref)
            analysis.observe(merged.commit, roots, ref)
            tip = target_index.resolve_use(ref)
            if tip.status != 'valid':
                continue
            if _invalid_call(ref, tip, target_index):
                continue
            final = final_index.resolve_use(ref)
            relevant = set(tip.files) | set(final.files)
            if not (relevant & changed_paths):
                continue
            reason = _broken(ref, tip, final, final_index)
            if reason is None:
                continue
            candidates = [label for label, _ in live if _changed_paths(summaries[label]) & relevant]
            culprits = tuple(sorted(candidates))
            exact = False
            for subset in [(), *(_subsets(candidates) if len(candidates) <= 6 else ())]:
                commit = trial(set(subset))
                if commit is None:
                    continue
                check_index = index(commit, roots)
                if _broken(ref, tip, check_index.resolve_use(ref), check_index) is not None:
                    culprits, exact = subset or (target,), True
                    break
            if not exact and len(candidates) > 3:
                limits_hit.add('max_candidates' if len(candidates) > 6 else 'max_group')
            symbol = f'{ref.module}.{ref.name}'
            if len(culprits) == 1:
                rule = 'CW001' if reason == 'undefined' else 'CW002'
                message = (f'`{symbol}` is used here but was removed in {culprits[0]}' if rule == 'CW001'
                           else f'`{symbol}` call is incompatible with {culprits[0]}: {reason}')
            else:
                rule = 'CW006'
                message = f'`{symbol}` is broken after merging {{{", ".join(culprits)}}}: {reason}; no single branch causes it'
            findings.append(CombinedFinding(rule, 'error', message, target, tuple(culprits), exact,
                                            None, ref.path, ref.line, 'integrated', symbol,
                                            hint=_call_hint(reason, final, final_index) if rule == 'CW002' else None))
    # Explain pairwise breakages repaired by another integrated branch.
    for (a, _), (b, _) in itertools.combinations(live, 2):
        if not interacts(summaries[a], summaries[b]):
            continue
        context = PairContext(repo, target_sha, summaries[a], summaries[b], False, [], analysis)
        pairwise = cw001.check(context) + cw002.check(context)
        for finding in pairwise:
            owner = finding.branch
            cause = finding.other_branch
            summary = summaries[owner]
            roots = summary.roots
            tip_index = index(summary.tip, roots)
            final_index = index(merged.commit, roots)
            refs = [r for r in analysis.semantic(summary).uses
                    if r.path == finding.path and r.line == finding.line
                    and f'{r.module}.{r.name}' == finding.symbol]
            for ref in refs:
                tip = tip_index.resolve_use(ref)
                if tip.status != 'valid':
                    continue
                if _invalid_call(ref, tip, tip_index):
                    continue
                final = final_index.resolve_use(ref)
                location = _location(repo, merged.commit, ref, roots, analysis)
                if final.status != 'valid' or _broken(ref, tip, final, final_index) is not None or location is None:
                    continue
                initial = trial({owner, cause})
                if initial is None:
                    continue
                initial_index = index(initial, roots)
                if _broken(ref, tip, initial_index.resolve_use(ref), initial_index) is None:
                    continue
                message = finding.message
                owner_commit = trial({owner})
                if owner_commit is not None:
                    owner_index = index(owner_commit, roots)
                    target_reason = _broken(ref, tip, owner_index.resolve_use(ref), owner_index)
                    if target_reason is not None:
                        cause = target
                        message = (f'`{finding.symbol}` is used here but was removed in {target}'
                                   if finding.rule == 'CW001' else
                                   f'`{finding.symbol}` call is incompatible with {target}: {target_reason}')
                relevant = set(tip.files) | set(final.files)
                candidates = [other for other, _ in live if other not in (owner, cause)
                              and _changed_paths(summaries[other]) & relevant]
                resolved = None
                exact = False
                if len(candidates) <= 6:
                    for subset in _subsets(candidates):
                        commit = trial({owner, cause} | set(subset))
                        if commit is None:
                            continue
                        fixed_index = index(commit, roots)
                        fixed = fixed_index.resolve_use(ref)
                        if fixed.status == 'valid' and _broken(ref, tip, fixed, fixed_index) is None:
                            resolved = subset
                            exact = True
                            break
                if resolved is None and candidates:
                    resolved = tuple(sorted(candidates))
                    if len(candidates) > 3:
                        limits_hit.add('max_candidates' if len(candidates) > 6 else 'max_group')
                if resolved is not None:
                    findings.append(CombinedFinding(finding.rule, 'warning', message,
                                                    owner, (cause,), exact, resolved,
                                                    finding.path, location[0], location[1],
                                                    finding.symbol,
                                                    limitations=('call signature unknown in integrated state',)
                                                    if ref.call and (not final_index.adapter.signature_known(final.binding)) else ()))
    # Retain pairwise duplicate definitions and migration collisions.
    for (a, _), (b, _) in itertools.combinations(live, 2):
        if not interacts(summaries[a], summaries[b]):
            continue
        context = PairContext(repo, target_sha, summaries[a], summaries[b], False, [], analysis)
        phase_findings = cw003.check(context)
        for adapter in analysis.adapters.values():
            phase_findings.extend(adapter.pairwise_rules(context))
        for f in phase_findings:
            findings.append(CombinedFinding(f.rule, f.severity, f.message, f.branch,
                                            (f.other_branch,), True, None, f.path, f.line,
                                            'integrated', f.symbol))
    # D8: only the earliest containing branch owns a shared visible use site.
    identities = {(f.branch, f.rule, f.path, f.line, f.symbol, f.culprits) for f in findings}
    findings = [f for f in findings if not any(
        (other, f.rule, f.path, f.line, f.symbol, f.culprits) in identities
        for other, other_sha in live
        if f.branch in run.shas and (other_sha, run.shas[f.branch]) in run.ancestors)]
    result = []
    for finding in consolidate(findings):
        advice = (finding.hint or _rename_hint(finding, run, merged.commit)
                  or hint(finding) or migration_hint(repo, merged.commit, finding))
        repro = reproduction(finding, target, branches, src, repro_repo)
        result.append(replace(finding, hint=advice, repro=repro,
                              limitations=finding_limitations(finding, bool(limits_hit))))
    result.sort(key=lambda f: (f.path, f.line, f.rule, f.branch,
                               f.culprits, f.symbol or '', f.message))
    limits = {'max_candidates': 6, 'max_group': 3, 'group_search_max_remaining': 8, 'hit': sorted(limits_hit)}
    if collect_coverage:
        analysis.track_state(merged.commit, [summaries[label] for label in merged.integrated])
    limitations = inspect(repo, [target_sha, *shas, merged.commit], src, analysis) if collect_coverage else {}
    coverage = 'bounded' if limits_hit else ('partial' if limitations else 'complete')
    return CombinedReport(target_sha, merged.integrated, merged.skipped, result,
                          coverage, limits, merged.commit, limitations)
