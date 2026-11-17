"""Best-effort, versioned on-disk cache for branch summaries."""

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, replace
from pathlib import Path

from . import __version__

_CACHE_SCHEMA = 3
from .git import FileChange
from .model import ApiChange, BranchSummary, CallShape, Param, Reference, Symbol


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


def _encode(summary):
    return _json_value({
        'schema_version': _CACHE_SCHEMA,
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


def _decode(data):
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


class SummaryCache:
    """Store summaries by tool version, base, tip, and ordered roots."""

    def __init__(self, directory):
        self.directory = Path(directory) / 'crosswire' / 'cache' / 'v1'

    def _path(self, base, tip, roots):
        key = json.dumps([_CACHE_SCHEMA, __version__, base, tip, list(roots)], separators=(',', ':'))
        return self.directory / (hashlib.sha256(key.encode()).hexdigest() + '.json')

    def get(self, label, base, tip, roots):
        """Load a valid entry, returning None for absent or damaged entries."""
        try:
            data = json.loads(self._path(base, tip, roots).read_text(encoding='utf-8'))
            if data.get('schema_version') != _CACHE_SCHEMA:
                return None
            summary = _decode(data)
            if (summary.base, summary.tip, summary.roots) != (base, tip, tuple(roots)):
                return None
            if _encode(summary) != data:
                return None
            return replace(summary, label=label)
        except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
            return None

    def put(self, summary):
        """Atomically persist an entry; caching failures never block analysis."""
        temporary = None
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix='.tmp-', dir=self.directory)
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(_encode(summary), stream, sort_keys=True, separators=(',', ':'))
            os.replace(temporary, self._path(summary.base, summary.tip, summary.roots))
        except (OSError, ValueError, TypeError):
            pass
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
