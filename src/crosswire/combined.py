"""Analyze the integrated state of an ordered set of branches."""

import itertools
from dataclasses import dataclass
from collections import Counter

from . import git
from .cache import SummaryCache
from .engine import PairContext, _Analysis
from .findings import consolidate
from .integrate import integrate
from .python_analyzer import cached_references, module_name_for_path, valid_syntax
from .rules import cw001, cw002, cw003, cw004
from .state import StateIndex


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


def _broken(ref, tip, final, final_index):
    if final.status == 'unknown' and tip.files:
        # Syntax errors remain unknown even if another previously consulted file was removed.
        for path in final.files:
            source = git.read_file(final_index.repo, final_index.commit, path)
            if source is not None:
                if not valid_syntax(source):
                    return None
        # A module that existed at the reference's tip and was removed is in-repo.
        if any(git.read_file(final_index.repo, final_index.commit, p) is None for p in tip.files):
            return 'undefined'
    if final.status == 'broken':
        return 'undefined'
    if final.status != 'valid':
        return None
    if (ref.call is not None and not ref.call.has_star and not ref.call.has_starstar
            and tip.symbol is not None and final.symbol is not None
            and tip.symbol.params is not None and final.symbol.params is not None
            and cw002.binding_error(ref.call, tip.symbol.params) is None):
        return cw002.binding_error(ref.call, final.symbol.params)
    return None


def _location(repo, commit, ref, roots):
    source = git.read_file(repo, commit, ref.path)
    if source is None:
        return ref.line, 'branch'
    module = module_name_for_path(ref.path, roots)
    if module is None:
        return None
    try:
        found = cached_references(source, module, ref.path,
                                   ref.path.endswith('/__init__.py') or ref.path == '__init__.py')
    except SyntaxError:
        return None
    matching = [r for r in found if (r.module, r.name, r.call) == (ref.module, ref.name, ref.call)]
    if not matching:
        return None
    chosen = min(matching, key=lambda r: (abs(r.line - ref.line), r.line))
    return chosen.line, 'integrated'


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


def analyze_combined(repo, branches, target, src=None, cache=True, min_branches=2):
    """Integrate branches and find new broken references in the final state."""
    repo = git.repo_root(repo)
    git.git_version(repo)
    if not target:
        raise git.GitError('--combined requires --target')
    if len(branches) < min_branches:
        raise git.GitError(f'at least {min_branches} branches are required')
    target_sha = git.resolve(repo, target)
    shas = [git.resolve(repo, b) for b in branches]
    if len(set(shas)) != len(shas):
        raise git.GitError('branches must resolve to distinct commits')
    ordered = list(zip(branches, shas))
    analysis = _Analysis(repo)
    disk = SummaryCache(git.common_dir(repo)) if cache else None
    summaries = {}
    for label, sha in ordered:
        base = git.merge_base(repo, sha, target_sha)
        if base is None:
            raise git.GitError(f'no merge base for {label} and {target}')
        files = git.list_files(repo, base) if src is None else ()
        roots = tuple(src) if src is not None else (('src', '.') if any(p.startswith('src/') for p in files) else ('.',))
        summary = disk.get(label, base, sha, roots) if disk else None
        if summary is None:
            failures = analysis.parse_failures
            summary = analysis.side(label, sha, base, roots)
            if disk and failures == analysis.parse_failures:
                disk.put(summary)
        summaries[label] = summary
    merged = integrate(repo, target_sha, ordered)
    integrated = set(merged.integrated)
    live = [(label, sha) for label, sha in ordered if label in integrated]
    final_indexes = {}
    tip_indexes = {}
    trial_indexes = {}
    def index(commit, roots):
        key = (commit, roots)
        if key not in trial_indexes:
            trial_indexes[key] = StateIndex(repo, commit, roots)
        return trial_indexes[key]
    def trial(labels):
        selected = [(label, sha) for label, sha in live if label in labels]
        result = integrate(repo, target_sha, selected)
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
            if len(candidates) <= 6:
                for subset in _subsets(candidates):
                    subset_set = set(subset)
                    prior = [(other, other_sha) for other, other_sha in ordered
                             if other in subset_set]
                    attempt = integrate(repo, target_sha, prior + [(label, sha)])
                    if (label in dict(attempt.skipped)
                            and all(other in attempt.integrated for other in subset)):
                        culprits, exact = subset, True
                        break
            if not exact:
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
        tip_index = tip_indexes.setdefault(label, StateIndex(repo, sha, roots))
        final_index = final_indexes.setdefault(roots, StateIndex(repo, merged.commit, roots))
        for ref in summary.references:
            tip = tip_index.resolve(ref.module, ref.name)
            if tip.status != 'valid':
                continue
            if (ref.call is not None and not ref.call.has_star and not ref.call.has_starstar
                    and tip.symbol is not None and tip.symbol.params is not None
                    and cw002.binding_error(ref.call, tip.symbol.params) is not None):
                continue
            final = final_index.resolve(ref.module, ref.name)
            reason = _broken(ref, tip, final, final_index)
            location = _location(repo, merged.commit, ref, roots)
            if reason is None or location is None:
                continue
            relevant = set(tip.files) | set(final.files)
            candidates = [other for other, _ in live if other != label and _changed_paths(summaries[other]) & relevant]
            culprits = tuple(sorted(candidates))
            exact = False
            if len(candidates) <= 6:
                for subset in _subsets(candidates):
                    commit = trial(set(subset) | {label})
                    if commit is None:
                        continue
                    trial_index = index(commit, roots)
                    if _broken(ref, tip, trial_index.resolve(ref.module, ref.name), trial_index) is not None:
                        culprits, exact = subset, True
                        break
            if not exact:
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
                                            ref.path, location[0], location[1], symbol))
    # Recheck occurrences already present on the target against the integrated state.
    target_files = git.list_files(repo, target_sha)
    roots = tuple(src) if src is not None else (('src', '.') if any(p.startswith('src/') for p in target_files) else ('.',))
    changed_paths = {path for change in git.changed_files(repo, target_sha, merged.commit)
                     for path in (change.path, change.old_path) if path}
    target_index = index(target_sha, roots)
    final_index = index(merged.commit, roots)
    for path in git.list_files(repo, merged.commit):
        module = module_name_for_path(path, roots)
        if module is None or git.read_file(repo, target_sha, path) is None:
            continue
        old = analysis.references(target_sha, path, module)
        new = analysis.references(merged.commit, path, module)
        if old is None or new is None:
            continue
        def ref_key(ref):
            return ref.path, ref.module, ref.name, ref.call
        remaining = Counter(ref_key(ref) for ref in old)
        for ref in sorted(new, key=lambda item: item.line):
            key = ref_key(ref)
            if not remaining[key]:
                continue
            remaining[key] -= 1
            tip = target_index.resolve(ref.module, ref.name)
            if tip.status != 'valid':
                continue
            if (ref.call is not None and not ref.call.has_star and not ref.call.has_starstar
                    and tip.symbol is not None and tip.symbol.params is not None
                    and cw002.binding_error(ref.call, tip.symbol.params) is not None):
                continue
            final = final_index.resolve(ref.module, ref.name)
            relevant = set(tip.files) | set(final.files)
            if not (relevant & changed_paths):
                continue
            reason = _broken(ref, tip, final, final_index)
            if reason is None:
                continue
            candidates = [label for label, _ in live if _changed_paths(summaries[label]) & relevant]
            culprits = tuple(sorted(candidates))
            exact = False
            if len(candidates) <= 6:
                for subset in _subsets(candidates):
                    commit = trial(set(subset))
                    if commit is None:
                        continue
                    check_index = index(commit, roots)
                    if _broken(ref, tip, check_index.resolve(ref.module, ref.name), check_index) is not None:
                        culprits, exact = subset, True
                        break
            if not exact:
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
                                            None, ref.path, ref.line, 'integrated', symbol))
    # Explain pairwise breakages repaired by another integrated branch.
    for (a, _), (b, _) in itertools.combinations(live, 2):
        context = PairContext(repo, target_sha, summaries[a], summaries[b], False, [], analysis)
        pairwise = cw001.check(context) + cw002.check(context)
        for finding in pairwise:
            owner = finding.branch
            cause = finding.other_branch
            summary = summaries[owner]
            roots = summary.roots
            tip_index = tip_indexes.setdefault(owner, StateIndex(repo, summary.tip, roots))
            final_index = final_indexes.setdefault(roots, StateIndex(repo, merged.commit, roots))
            refs = [r for r in summary.references
                    if r.path == finding.path and r.line == finding.line
                    and f'{r.module}.{r.name}' == finding.symbol]
            for ref in refs:
                tip = tip_index.resolve(ref.module, ref.name)
                if tip.status != 'valid':
                    continue
                if (ref.call is not None and not ref.call.has_star and not ref.call.has_starstar
                        and tip.symbol is not None and tip.symbol.params is not None
                        and cw002.binding_error(ref.call, tip.symbol.params) is not None):
                    continue
                final = final_index.resolve(ref.module, ref.name)
                location = _location(repo, merged.commit, ref, roots)
                if final.status != 'valid' or _broken(ref, tip, final, final_index) is not None or location is None:
                    continue
                initial = trial({owner, cause})
                if initial is None:
                    continue
                initial_index = index(initial, roots)
                if _broken(ref, tip, initial_index.resolve(ref.module, ref.name), initial_index) is None:
                    continue
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
                        fixed = fixed_index.resolve(ref.module, ref.name)
                        if fixed.status == 'valid' and _broken(ref, tip, fixed, fixed_index) is None:
                            resolved = subset
                            exact = True
                            break
                if resolved is None and candidates:
                    resolved = tuple(sorted(candidates))
                    limits_hit.add('max_candidates' if len(candidates) > 6 else 'max_group')
                if resolved is not None:
                    findings.append(CombinedFinding(finding.rule, 'warning', finding.message,
                                                    owner, (cause,), exact, resolved,
                                                    finding.path, location[0], location[1],
                                                    finding.symbol))
    # Retain pairwise duplicate definitions and migration collisions.
    for (a, _), (b, _) in itertools.combinations(live, 2):
        context = PairContext(repo, target_sha, summaries[a], summaries[b], False, [], analysis)
        for rule in (cw003, cw004):
            for f in rule.check(context):
                findings.append(CombinedFinding(f.rule, f.severity, f.message, f.branch,
                                                (f.other_branch,), True, None, f.path, f.line,
                                                'integrated', f.symbol))
    result = sorted(consolidate(findings), key=lambda f: (f.path, f.line, f.rule, f.branch,
                                                       f.culprits, f.symbol or '', f.message))
    limits = {'max_candidates': 6, 'max_group': 3, 'group_search_max_remaining': 8, 'hit': sorted(limits_hit)}
    return CombinedReport(target_sha, merged.integrated, merged.skipped, result,
                          'bounded' if limits_hit else 'complete', limits, merged.commit)
