from collections import Counter, defaultdict
from .model import ApiChange

def api_changes(base, tip):
    result = []
    added = [v for k, v in tip.items() if k not in base]
    for name, old in base.items():
        new = tip.get(name)
        if new is None:
            matches = [s.qualname for s in added if s.module == old.module and s.kind == old.kind and s.shape == old.shape]
            result.append(ApiChange('removed', old.module, name, old, None, matches[0] if len(matches) == 1 else None))
        elif old.params is not None and new.params is not None and old.params != new.params:
            result.append(ApiChange('signature_changed', old.module, name, old, new, None))
    return result

def added_references(base_refs, tip_refs):
    def key(r): return (r.path, r.module, r.name, r.call)
    counts = Counter(map(key, base_refs))
    groups = defaultdict(list)
    for ref in tip_refs: groups[key(ref)].append(ref)
    result = []
    for k, refs in groups.items():
        n = len(refs) - counts[k]
        if n > 0: result.extend(sorted(refs, key=lambda r: r.line)[-n:])
    return sorted(result, key=lambda r: (r.path, r.line, r.module, r.name))
