from collections import Counter, defaultdict
from .lang.python.diffing import api_changes  # T21 compatibility facade


def added_references(base_refs, tip_refs):
    """Added references."""
    def key(r):
        """Key."""
        return (r.language, r.path, r.module, r.name, r.call)
    counts = Counter(map(key, base_refs))
    groups = defaultdict(list)
    for ref in tip_refs:
        groups[key(ref)].append(ref)
    result = []
    for k, refs in groups.items():
        n = len(refs) - counts[k]
        if n > 0:
            result.extend(sorted(refs, key=lambda r: r.line)[-n:])
    return sorted(result, key=lambda r: (r.path, r.line, r.module, r.name, r.language))
