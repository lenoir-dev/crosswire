from ..model import Finding
from collections import defaultdict
RULE_ID = 'CW001'
SEVERITY = 'error'


def check(ctx):
    """Check."""
    out = []
    for cause, affected in ((ctx.a, ctx.b), (ctx.b, ctx.a)):
        for data in affected.semantics:
            adapter = ctx.analysis.adapters[data.language]
            changes = defaultdict(list)
            for change in ctx.analysis.semantic(cause, data.language).api:
                changes[change.identity].append(change)
            for ref in data.uses:
                for change in changes.get(ref.target, ()):
                    if (change.kind != 'removed' or change.identity != ref.target
                            or not adapter.member_resolvable(change.identity)):
                        continue
                    if ref.target in data.redefined:
                        continue
                    symbol = f'{ref.module}.{ref.name}'
                    msg = f'`{symbol}` is used here but was removed in {cause.label}'
                    if change.rename_hint:
                        msg += f' (renamed to `{ref.module}.{change.rename_hint}`?)'
                    out.append(Finding(RULE_ID, SEVERITY, msg, affected.label,
                                       cause.label, ref.path, ref.line, symbol))
    return out
