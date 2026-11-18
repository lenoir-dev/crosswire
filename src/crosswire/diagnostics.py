"""Evidence-based finding advice and reproduction commands."""

import shlex


def hint(finding):
    """Compatibility facade for language-owned remediation advice."""
    from .lang import adapters_for
    return next((advice for adapter in adapters_for(None).values()
                 if (advice := adapter.hint(finding))), None)


def finding_limitations(finding, bound_hit=False):
    """Describe concrete uncertainties attached to this finding."""
    caveats = list(finding.limitations)
    if hasattr(finding, 'culprits_exact') and not finding.culprits_exact:
        caveats.append('culprits not exact (search bound hit)' if bound_hit else 'culprits not exact')
    if getattr(finding, 'location', None) == 'branch':
        caveats.append('location from branch tip')
    elif finding.rule == 'CW005' and not hasattr(finding, 'location'):
        caveats.append('file-level location; conflict line unavailable')
    return tuple(dict.fromkeys(caveats))


def reproduction(finding, target, branches, src, repo=None):
    """Build a shell-safe reproducer only when the culprit set is exact."""
    if not finding.culprits_exact or finding.resolved_by is not None:
        return None
    wanted = set(finding.culprits)
    if finding.branch != target:
        wanted.add(finding.branch)
    ordered = [branch for branch in branches if branch in wanted and branch != target]
    if not ordered:
        return None
    args = ['crosswire', 'check']
    if repo is not None:
        args.extend(['--repo', str(repo)])
    args.extend(['--target', target, '--combined'])
    for root in src or ():
        args.extend(['--src', root])
    args.extend(ordered)
    return shlex.join(args)


def migration_hint(repo, rev, finding):
    """Compatibility name for adapter-owned state-dependent advice."""
    from .lang import adapters_for
    from .lang.base import Snapshot
    return next((advice for adapter in adapters_for(repo).values()
                 if (advice := adapter.state_hint(Snapshot(repo, rev), finding))), None)
