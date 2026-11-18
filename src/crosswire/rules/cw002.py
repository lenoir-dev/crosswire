from ..model import Finding
from collections import defaultdict
RULE_ID = 'CW002'
SEVERITY = 'error'


# Retained import facades; the core checks calls only through the adapter.
from ..lang.python.calls import binding_error, keyword_hint


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
                if ref.call is None:
                    continue
                for change in changes.get(ref.target, ()):
                    if (change.kind != 'signature_changed' or change.identity != ref.target
                            or not adapter.member_resolvable(change.identity)):
                        continue
                    verdict = adapter.check_call(ref, change.old, change.new)
                    if verdict.status == 'broken':
                        symbol = f'{ref.module}.{ref.name}'
                        out.append(Finding(RULE_ID, SEVERITY,
                            f'`{symbol}` call is incompatible with {cause.label}: {verdict.detail}',
                            affected.label, cause.label, ref.path, ref.line, symbol,
                            hint=adapter.call_hint(verdict, change.new)))
    return out
