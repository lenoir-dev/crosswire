from ..model import Finding
RULE_ID = 'CW003'
SEVERITY = 'warning'


def check(ctx):
    """Check."""
    cause, affected = sorted((ctx.a, ctx.b), key=lambda s: s.label)
    out = []
    for data in cause.semantics:
        adapter = ctx.analysis.adapters[data.language]
        other = ctx.analysis.semantic(affected, data.language)
        for identity in data.definitions.keys() & other.definitions.keys():
            group = other.definitions[identity]
            policy = adapter.duplicate_policy(group.declarations[0].kind)
            if policy == 'ignore':
                continue
            if policy == 'different-definition-warning' and ctx.definitions_equal(cause, affected, identity):
                continue
            symbol = f'{identity.namespace.name}.{identity.name}'
            loc = group.declarations[0].span
            out.append(Finding(RULE_ID, 'error' if policy == 'error' else SEVERITY,
                f'`{symbol}` is independently defined in both branches',
                affected.label, cause.label, loc.path, loc.line, symbol))
    return out
