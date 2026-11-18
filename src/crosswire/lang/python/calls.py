"""Python argument binding and evidence-based call hints."""

def binding_error(call, params):
    """Binding error."""
    positional = [p for p in params if p.kind in ('posonly', 'pos')]
    vararg = any(p.kind == 'vararg' for p in params)
    varkw = any(p.kind == 'varkw' for p in params)
    if call.positional > len(positional) and not vararg:
        return 'too many positional arguments'
    assigned = {p.name for p in positional[:call.positional]}
    named = {
        p.name: p for p in params if p.kind in (
            'posonly',
            'pos',
            'kwonly')}
    seen = set()
    for kw in call.keywords:
        if kw in seen:
            return f'duplicate value for {kw}'
        seen.add(kw)
        p = named.get(kw)
        if p and p.kind == 'posonly':
            if varkw:
                continue
            return f'positional-only argument passed as keyword: {kw}'
        if p is None:
            if not varkw:
                return f'unknown keyword argument: {kw}'
        elif kw in assigned:
            return f'duplicate value for {kw}'
        else:
            assigned.add(kw)
    for p in params:
        if p.kind in ('posonly', 'pos',
                      'kwonly') and not p.has_default and p.name not in assigned:
            return f'missing required argument: {p.name}'
    return None


def keyword_hint(reason, params):
    """Advise a keyword only when the new signature accepts it."""
    prefix = 'missing required argument: '
    if reason.startswith(prefix):
        name = reason[len(prefix):]
        if any(p.name == name and p.kind in ('pos', 'kwonly') for p in params):
            return f'pass `{name}=`'
    return None

