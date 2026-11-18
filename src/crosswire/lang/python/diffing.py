"""Python API-change semantics."""

from ...model import ApiChange

def api_changes(base, tip):
    """Api changes."""
    result = []
    added = [v for k, v in tip.items() if k not in base]
    for name, old in base.items():
        new = tip.get(name)
        if new is None:
            matches = [s.qualname for s in added if s.module ==
                       old.module and s.kind == old.kind and s.shape == old.shape]
            result.append(
                ApiChange(
                    'removed',
                    old.module,
                    name,
                    old,
                    None,
                    matches[0] if len(matches) == 1 else None))
        elif old.params is not None and new.params is not None and old.params != new.params:
            result.append(
                ApiChange(
                    'signature_changed',
                    old.module,
                    name,
                    old,
                    new,
                    None))
    return result

