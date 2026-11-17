"""Construct a bounded, deterministic merge plan from integrated states."""

import itertools
from dataclasses import asdict, replace

from . import git
from .combined import AnalysisRun, CombinedFinding, analyze_combined
from .diagnostics import hint, migration_hint, reproduction
from .coverage import inspect
from .rules.cw004 import _DJANGO, revisions


def _key(finding):
    return finding.rule, finding.path, finding.symbol or finding.path


def _describe(finding):
    """Describe a concrete error and its known causes without guessing."""
    name = f'`{finding.symbol}`' if finding.symbol else finding.path
    causes = f', culprits {", ".join(finding.culprits)}' if finding.culprits else ''
    return f'{name} ({finding.rule}{causes})'


def _migration_findings(repo, target, state, labels, summaries=None, ancestors=None):
    """Find collisions in the state involving at least one added migration."""
    if summaries is None:
        run = AnalysisRun(repo, labels, target, cache=False)
        summaries = run.summaries
        ancestors = run.ancestors
    if ancestors is None:
        ancestors = git.ancestor_relations(repo, [summaries[label].tip for label in labels])
    changes = git.changed_files(repo, target, state)
    added = {change.path for change in changes if change.status == 'A'}
    if not added:
        return []
    files = [path for path in git.list_files(repo, state) if path.endswith('.py')]
    django = [(path, _DJANGO.match(path)) for path in files]
    django = [(path, match) for path, match in django if match]
    alembic = []
    for path in files:
        if 'versions' in path.split('/')[:-1]:
            try:
                source = git.read_file(repo, state, path)
            except git.SkippedBlob:
                continue
            alembic.append((path, revisions(path, source or '')))
    owners = {}
    for label in labels:
        for path in summaries[label].migrations:
            owners.setdefault(path, []).append(label)
    for path, names in owners.items():
        owners[path] = [name for name in names if not any(
            (summaries[other].tip, summaries[name].tip) in ancestors for other in names)]

    def attribution(a, b):
        causes = set(owners.get(a, ())) | set(owners.get(b, ()))
        owner = next((label for label in reversed(labels) if label in causes), '')
        return owner, tuple(sorted(causes))

    findings = []
    for (a, am), (b, bm) in itertools.combinations(django, 2):
        if (a in added or b in added) and am.groups() == bm.groups():
            path = b if b in added else a
            owner, causes = attribution(a, b)
            findings.append(CombinedFinding('CW004', 'error', f'migration number {am.group(2)} collides with {a if path == b else b}',
                                            owner, causes, True, None,
                                            path, 1, 'integrated', None))
    for (a, av), (b, bv) in itertools.combinations(alembic, 2):
        common = av & bv
        if common and (a in added or b in added):
            path = b if b in added else a
            owner, causes = attribution(a, b)
            findings.append(CombinedFinding('CW004', 'error', f'Alembic revisions share down_revision {", ".join(sorted(common))}',
                                            owner, causes, True, None,
                                            path, 1, 'integrated', None))
    return findings


def plan(repo, branches, target, src=None, cache=True, repro_repo=None):
    """Choose safe individual branches or small atomic groups in user order."""
    if not target:
        raise git.GitError('plan requires --target')
    if not branches:
        raise git.GitError('at least one branch is required')
    run = AnalysisRun(repo, branches, target, src, cache)
    repo = run.repo
    target_sha = run.target_sha
    shas = run.shas
    contained = {label: [] for label in branches}
    dependencies = {label: set() for label in branches}
    for a, b in itertools.permutations(branches, 2):
        if (shas[a], shas[b]) in run.ancestors:
            contained[a].append(b)
            dependencies[b].add(a)
    contained = {label: sorted(names) for label, names in contained.items()}
    states = {}
    hit = set()
    final_limitations = {}

    def state(labels):
        key = tuple(labels)
        if key not in states:
            report = analyze_combined(repo, list(labels), target, src, cache, min_branches=0, collect_coverage=False, _run=run, repro_repo=repro_repo)
            extra = _migration_findings(repo, target_sha, report.commit, labels, run.summaries, run.ancestors)
            extra = [replace(f, hint=hint(f) or migration_hint(repo, report.commit, f),
                             repro=reproduction(f, target, labels, src, repro_repo)) for f in extra]
            findings = [f for f in report.findings if f.rule != 'CW004'] + extra
            states[key] = report, findings
            hit.update(report.limits['hit'])
        return states[key]

    def errors(labels):
        return {_key(f) for f in state(labels)[1] if f.severity == 'error'}

    def legal(group, placed):
        available = set(placed)
        for label in group:
            if not dependencies[label] <= available:
                return False
            available.add(label)
        return True

    placed = []
    remaining = list(branches)
    steps = []
    blocked = []
    deferred_history = {}
    while remaining:
        before = errors(placed)
        selected = None
        reasons = {}
        for label in remaining:
            if not legal((label,), placed):
                continue
            report, findings = state(placed + [label])
            new = [f for f in findings if f.severity == 'error' and _key(f) not in before]
            if not new and label in report.integrated:
                selected = (label,)
                break
            reasons[label] = new
            if new:
                deferred_history[label] = new
        if selected is None:
            if len(remaining) <= 8:
                for size in (2, 3):
                    for group in itertools.combinations(remaining, size):
                        if not legal(group, placed):
                            continue
                        report, findings = state(placed + list(group))
                        if all(label in report.integrated for label in group) and not (errors(placed + list(group)) - before):
                            selected = group
                            break
                    if selected is not None:
                        break
                if selected is None and len(remaining) > 3:
                    hit.add('max_group')
            else:
                hit.add('group_search_max_remaining')
        if selected is None:
            for label in remaining:
                report, findings = state(placed + [label])
                new = [f for f in findings if f.severity == 'error' and _key(f) not in before]
                entry = {'branch': label, 'findings': [asdict(f) for f in new]}
                conflicts = [f for f in new if f.rule == 'CW005']
                if conflicts:
                    causes = sorted({cause for f in conflicts for cause in f.culprits})
                    paths = sorted({f.path for f in conflicts})
                    entry['hint'] = (f"rebase {label} onto {', '.join(causes) if causes else target} "
                                     f"(conflicts in {', '.join(paths)})")
                elif any(f.rule in ('CW001', 'CW002', 'CW006') for f in new):
                    entry['hint'] = 'Restore the referenced API or merge a compatible fix first.'
                elif dependencies[label] - set(placed):
                    entry['hint'] = 'Place prerequisite branches first: ' + ', '.join(sorted(dependencies[label] - set(placed)))
                blocked.append(entry)
            break
        together = len(selected) > 1
        after = placed + list(selected)
        details = []
        if together:
            for member in selected:
                if not legal((member,), placed):
                    missing = sorted(dependencies[member] - set(placed))
                    details.append(f"{member} requires {', '.join(missing)} first")
                    continue
                individual = reasons.get(member)
                if individual is None:
                    individual = [f for f in state(placed + [member])[1]
                                  if f.severity == 'error' and _key(f) not in before]
                if individual:
                    details.append(f'{member} alone breaks {_describe(individual[0])}')
                else:
                    details.append(f'{member} alone cannot be integrated')
        selected_first = min(remaining.index(label) for label in selected)
        earlier = [label for label in remaining[:selected_first] if label not in selected]
        for label in earlier:
            if not legal((label,), after):
                continue
            prior_report, prior_findings = state(placed + [label])
            later_report, later_findings = state(after + [label])
            prior_errors = {_key(f) for f in prior_findings if f.severity == 'error'} - before
            later_errors = {_key(f) for f in later_findings if f.severity == 'error'} - errors(after)
            if not ((prior_errors - later_errors) or
                    (label not in prior_report.integrated and label in later_report.integrated)):
                continue
            findings = reasons.get(label, [])
            resolved = [f for f in findings if _key(f) in prior_errors - later_errors]
            if resolved:
                details.append(f'placed before {label}: {label} would break {_describe(resolved[0])}')
            else:
                details.append(f'placed before {label}: {label} cannot be integrated yet')
        for label, previous in list(deferred_history.items()):
            if label in selected or label not in remaining or not legal((label,), after):
                continue
            trial_report, trial_findings = state(after + [label])
            if label not in trial_report.integrated:
                continue
            later = {_key(f) for f in trial_findings if f.severity == 'error'}
            resolved = [f for f in previous if _key(f) not in later]
            for finding in resolved:
                details.append(f'resolves {finding.rule} of {finding.branch} ({finding.symbol or finding.path})')
            if resolved:
                deferred_history[label] = [f for f in previous if _key(f) in later]
        if together:
            reason = 'clean only together: ' + '; '.join(details)
        else:
            reason = '; '.join(details) if details else 'no new errors in the integrated state'
        steps.append({'branches': list(selected), 'together': together, 'reason': reason})
        placed.extend(selected)
        remaining = [label for label in remaining if label not in selected]
    final_report, _ = state(placed)
    run.analysis.track_state(final_report.commit, [run.summaries[label] for label in final_report.integrated])
    final_limitations = inspect(repo, [target_sha, *shas.values(), final_report.commit], src, run.analysis)
    limits = {'max_candidates': 6, 'max_group': 3, 'group_search_max_remaining': 8, 'hit': sorted(hit)}
    return {'version': 2, 'tool': 'crosswire', 'mode': 'plan', 'target': target_sha,
            'steps': steps, 'blocked': blocked, 'contained_in': contained,
            'summary': {'placed': len(placed), 'blocked': len(blocked)},
            'coverage': 'bounded' if hit else ('partial' if final_limitations else 'complete'),
            'limitations': final_limitations, 'limits': limits}
