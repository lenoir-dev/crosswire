from ..model import Finding
RULE_ID = 'CW005'
SEVERITY = 'error'


def check(ctx):
    """Report textual conflicts in a branch-order-independent orientation."""
    other, branch = sorted((ctx.a.label, ctx.b.label))
    return [
        Finding(RULE_ID, SEVERITY, f'textual conflict with {other}',
                branch, other, path, 1, None)
        for path in ctx.conflicts
    ]
