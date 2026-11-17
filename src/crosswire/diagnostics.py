"""Evidence-based finding advice and reproduction commands."""

import re
import shlex


def hint(finding):
    """Give actionable advice only where the finding provides evidence."""
    rule = finding.rule
    symbol = finding.symbol
    culprits = getattr(finding, 'culprits', ()) or ()
    other = getattr(finding, 'other_branch', None)
    resolved = getattr(finding, 'resolved_by', None)
    if rule in ('CW001', 'CW002') and resolved:
        return f"merge {', '.join(resolved)} first"
    if rule == 'CW001':
        renamed = re.search(r'\(renamed to `([^`]+)`\?\)', finding.message)
        if renamed:
            return f'use `{renamed.group(1)}`'
        if symbol:
            return f'restore or re-export `{symbol}`'
    if rule == 'CW003':
        return 'keep one definition'
    if rule == 'CW004' and 'Alembic' in finding.message:
        return 'add a merge revision'
    if rule == 'CW005':
        causes = culprits or ((other,) if other else ())
        if causes:
            return f"rebase {finding.branch} onto {', '.join(causes)}"
    if rule == 'CW006' and culprits:
        return f"merge {', '.join(culprits)} together with a compatibility shim"
    return None


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
    """Calculate a free Django migration number from an actual Git tree."""
    if finding.rule != 'CW004' or 'Alembic' in finding.message:
        return None
    match = re.fullmatch(r'(.*(?:^|/)migrations)/(\d{4})_([^/]+\.py)', finding.path)
    if not match:
        return None
    directory, number, suffix = match.groups()
    from . import git
    existing = set()
    for path in git.list_files(repo, rev, directory):
        other = re.fullmatch(re.escape(directory) + r'/(\d{4})_[^/]+\.py', path)
        if other:
            existing.add(int(other.group(1)))
    next_number = int(number) + 1
    while next_number in existing:
        next_number += 1
    if next_number > 9999:
        return None
    return f'renumber `{finding.path}` to `{directory}/{next_number:04d}_{suffix}`'
