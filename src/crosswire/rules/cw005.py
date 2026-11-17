from ..model import Finding
RULE_ID = 'CW005'
SEVERITY = 'error'

def check(ctx):
    return [Finding(RULE_ID, SEVERITY, f'textual conflict with {ctx.a.label}', ctx.b.label, ctx.a.label, path, 1, None) for path in ctx.conflicts]
