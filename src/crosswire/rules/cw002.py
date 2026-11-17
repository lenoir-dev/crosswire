from ..model import Finding
RULE_ID = 'CW002'
SEVERITY = 'error'

def binding_error(call, params):
    positional = [p for p in params if p.kind in ('posonly', 'pos')]
    vararg = any(p.kind == 'vararg' for p in params)
    varkw = any(p.kind == 'varkw' for p in params)
    if call.positional > len(positional) and not vararg: return 'too many positional arguments'
    assigned = {p.name for p in positional[:call.positional]}
    named = {p.name: p for p in params if p.kind in ('posonly', 'pos', 'kwonly')}
    seen = set()
    for kw in call.keywords:
        if kw in seen: return f'duplicate value for {kw}'
        seen.add(kw)
        p = named.get(kw)
        if p and p.kind == 'posonly':
            if varkw: continue
            return f'positional-only argument passed as keyword: {kw}'
        if p is None:
            if not varkw: return f'unknown keyword argument: {kw}'
        elif kw in assigned: return f'duplicate value for {kw}'
        else: assigned.add(kw)
    for p in params:
        if p.kind in ('posonly', 'pos', 'kwonly') and not p.has_default and p.name not in assigned:
            return f'missing required argument: {p.name}'
    return None

def check(ctx):
    out = []
    for cause, affected in ((ctx.a, ctx.b), (ctx.b, ctx.a)):
        for ref in affected.references:
            if not ref.call or ref.call.has_star or ref.call.has_starstar: continue
            for change in cause.api.get(ref.module, []):
                if change.kind != 'signature_changed' or change.qualname != ref.name or '.' in change.qualname: continue
                if binding_error(ref.call, change.old.params): continue
                reason = binding_error(ref.call, change.new.params)
                if reason:
                    symbol = f'{ref.module}.{ref.name}'
                    out.append(Finding(RULE_ID, SEVERITY, f'`{symbol}` call is incompatible with {cause.label}: {reason}', affected.label, cause.label, ref.path, ref.line, symbol))
    return out
