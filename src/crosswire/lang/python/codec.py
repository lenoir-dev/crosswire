"""Versioned Python summary payload codec; never serializes adapter ASTs."""

from dataclasses import asdict
from ...git import FileChange
from ...model import ApiChange, BranchSummary, CallShape, Param, Reference, Symbol


def _symbol(data):
    params = data['params']
    if params is not None:
        params = tuple(Param(**p) for p in params)
    return Symbol(**{**data, 'params': params})


def _change(data):
    return ApiChange(**{**data, 'old': _symbol(data['old']),
                        'new': _symbol(data['new']) if data['new'] is not None else None})


def _reference(data):
    call = data['call']
    if call is not None:
        call = CallShape(**{**call, 'keywords': tuple(call['keywords'])})
    return Reference(**{**data, 'call': call})


def _json_value(value):
    """Convert nested tuples from dataclasses to JSON-compatible lists."""
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    return value


def encode(summary):
    return _json_value({
        'label': summary.label,
        'tip': summary.tip,
        'base': summary.base,
        'roots': list(summary.roots),
        'changes': [asdict(c) for c in summary.changes],
        'api': {m: [asdict(c) for c in changes] for m, changes in summary.api.items()},
        'references': [asdict(r) for r in summary.references],
        'definitions': {m: {n: asdict(s) for n, s in defs.items()}
                        for m, defs in summary.definitions.items()},
        'redefined': [list(x) for x in sorted(summary.redefined)],
        'migrations': summary.migrations,
        'touched_modules': sorted(summary.touched_modules),
        'referenced_modules': sorted(summary.referenced_modules),
    })


def decode(data):
    return BranchSummary(
        label=data['label'], tip=data['tip'], base=data['base'],
        roots=tuple(data['roots']),
        changes=tuple(FileChange(**c) for c in data['changes']),
        api={m: tuple(_change(c) for c in changes) for m, changes in data['api'].items()},
        references=tuple(_reference(r) for r in data['references']),
        definitions={m: {n: _symbol(s) for n, s in defs.items()}
                     for m, defs in data['definitions'].items()},
        redefined=frozenset(tuple(x) for x in data['redefined']),
        migrations=data['migrations'],
        touched_modules=frozenset(data['touched_modules']),
        referenced_modules=frozenset(data['referenced_modules']),
    )

