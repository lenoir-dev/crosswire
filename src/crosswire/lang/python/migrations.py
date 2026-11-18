from ...parsing import PARSE_ERRORS
import ast
import re
from ...model import Finding
from ...git import SkippedBlob
from ..base import Snapshot
RULE_ID = 'CW004'
SEVERITY = 'error'
_DJANGO = re.compile(r'^(.*(?:^|/)migrations)/(\d{4})_[^/]+\.py$')


def revisions(path, source):
    """Revisions."""
    if 'versions' not in path.split('/')[:-1]:
        return set()
    try:
        tree = ast.parse(source)
    except PARSE_ERRORS:
        return set()
    value = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name)
                                                and t.id == 'down_revision' for t in node.targets):
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == 'down_revision':
            value = node.value
    if value is None:
        return set()
    try:
        value = ast.literal_eval(value)
    except (ValueError, TypeError, RecursionError, MemoryError):
        return set()
    if isinstance(value, str):
        return {value} - {''}
    if isinstance(value, (tuple, list)) and all(isinstance(x, str)
                                                for x in value):
        return set(value) - {''}
    return set()


def check(ctx):
    """Check."""
    cause, affected = sorted((ctx.a, ctx.b), key=lambda s: s.label)
    out = []
    for ap, av in sorted(cause.migrations.items()):
        for bp, bv in sorted(affected.migrations.items()):
            if ap == bp:
                continue
            a, b = _DJANGO.match(ap), _DJANGO.match(bp)
            if a and b and a.groups() == b.groups():
                out.append(
                    Finding(
                        RULE_ID,
                        SEVERITY,
                        f'migration number {a.group(2)} also added in {cause.label}: {ap}',
                        affected.label,
                        cause.label,
                        bp,
                        1,
                        None))
            common = revisions(ap, av) & revisions(bp, bv)
            if common:
                out.append(
                    Finding(
                        RULE_ID,
                        SEVERITY,
                        f'Alembic revisions share down_revision {", ".join(sorted(common))} with {ap} in {cause.label}',
                        affected.label,
                        cause.label,
                        bp,
                        1,
                        None))
    return out


def state_findings(repo, target, state, labels, summaries=None, ancestors=None):
    """Find collisions in the state involving at least one added migration."""
    from ...combined import CombinedFinding
    import itertools
    snapshot = Snapshot(repo, state)
    if summaries is None:
        from ...combined import AnalysisRun
        run = AnalysisRun(repo, labels, target, cache=False)
        summaries = run.summaries
        ancestors = run.ancestors
    if ancestors is None:
        ancestors = snapshot.ancestors([summaries[label].tip for label in labels])
    changes = snapshot.changes_from(target)
    added = {change.path for change in changes if change.status == 'A'}
    if not added:
        return []
    files = [path for path in snapshot.list() if path.endswith('.py')]
    django = [(path, _DJANGO.match(path)) for path in files]
    django = [(path, match) for path, match in django if match]
    alembic = []
    for path in files:
        if 'versions' in path.split('/')[:-1]:
            try:
                source = snapshot.read(path)
            except SkippedBlob:
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



def migration_hint(repo, rev, finding):
    """Calculate a free Django migration number from an actual Git tree."""
    if finding.rule != 'CW004' or 'Alembic' in finding.message:
        return None
    match = re.fullmatch(r'(.*(?:^|/)migrations)/(\d{4})_([^/]+\.py)', finding.path)
    if not match:
        return None
    directory, number, suffix = match.groups()
    snapshot = Snapshot(repo, rev)
    existing = set()
    for path in snapshot.list(directory):
        other = re.fullmatch(re.escape(directory) + r'/(\d{4})_[^/]+\.py', path)
        if other:
            existing.add(int(other.group(1)))
    next_number = int(number) + 1
    while next_number in existing:
        next_number += 1
    if next_number > 9999:
        return None
    return f'renumber `{finding.path}` to `{directory}/{next_number:04d}_{suffix}`'
