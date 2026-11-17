from ..model import Finding
RULE_ID = 'CW001'
SEVERITY = 'error'


def check(ctx):
    """Check."""
    out = []
    for cause, affected in ((ctx.a, ctx.b), (ctx.b, ctx.a)):
        for ref in affected.references:
            for change in cause.api.get(ref.module, []):
                if change.kind != 'removed' or change.qualname != ref.name or '.' in change.qualname:
                    continue
                if (ref.module, ref.name) in affected.redefined:
                    continue
                symbol = f'{ref.module}.{ref.name}'
                msg = f'`{symbol}` is used here but was removed in {cause.label}'
                if change.rename_hint:
                    msg += f' (renamed to `{ref.module}.{change.rename_hint}`?)'
                out.append(
                    Finding(
                        RULE_ID,
                        SEVERITY,
                        msg,
                        affected.label,
                        cause.label,
                        ref.path,
                        ref.line,
                        symbol))
    return out
