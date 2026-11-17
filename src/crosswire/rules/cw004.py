import ast
import re
from ..model import Finding
RULE_ID = 'CW004'
SEVERITY = 'error'
_DJANGO = re.compile(r'^(.*(?:^|/)migrations)/(\d{4})_[^/]+\.py$')

def revisions(path, source):
    if 'versions' not in path.split('/')[:-1]: return set()
    try: tree = ast.parse(source)
    except SyntaxError: return set()
    value = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'down_revision' for t in node.targets): value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == 'down_revision': value = node.value
    if value is None: return set()
    try: value = ast.literal_eval(value)
    except (ValueError, TypeError): return set()
    if isinstance(value, str): return {value} - {''}
    if isinstance(value, (tuple, list)) and all(isinstance(x, str) for x in value): return set(value) - {''}
    return set()

def check(ctx):
    cause, affected = sorted((ctx.a, ctx.b), key=lambda s: s.label)
    out = []
    for ap, av in sorted(cause.migrations.items()):
        for bp, bv in sorted(affected.migrations.items()):
            if ap == bp: continue
            a, b = _DJANGO.match(ap), _DJANGO.match(bp)
            if a and b and a.groups() == b.groups():
                out.append(Finding(RULE_ID, SEVERITY, f'migration number {a.group(2)} also added in {cause.label}: {ap}', affected.label, cause.label, bp, 1, None))
            common = revisions(ap, av) & revisions(bp, bv)
            if common:
                out.append(Finding(RULE_ID, SEVERITY, f'Alembic revisions share down_revision {", ".join(sorted(common))} with {ap} in {cause.label}', affected.label, cause.label, bp, 1, None))
    return out
