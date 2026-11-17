from ..model import Finding
RULE_ID = 'CW003'
SEVERITY = 'warning'

def check(ctx):
    cause, affected = sorted((ctx.a, ctx.b), key=lambda s: s.label)
    out = []
    for module in cause.definitions.keys() & affected.definitions.keys():
        for name in cause.definitions[module].keys() & affected.definitions[module].keys():
            if cause.dumps.get(module, {}).get(name) == affected.dumps.get(module, {}).get(name): continue
            symbol = f'{module}.{name}'
            loc = affected.definitions[module][name]
            out.append(Finding(RULE_ID, SEVERITY, f'`{symbol}` is independently defined in both branches', affected.label, cause.label, loc.path, loc.line, symbol))
    return out
