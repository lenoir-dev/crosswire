"""Best-effort, versioned on-disk cache for branch summaries."""

import hashlib
import json
import os
import tempfile
from dataclasses import replace
from pathlib import Path

from . import __version__

from .lang import adapters_for
from .lang.base import ADAPTER_API_VERSION, Snapshot

_CACHE_SCHEMA = 4


class SummaryCache:
    """Store summaries by tool version, base, tip, and ordered roots."""

    def __init__(self, directory, adapters=None, repo=None):
        self.repo = repo if repo is not None else directory
        self.adapters = adapters if adapters is not None else adapters_for(self.repo)
        self.directory = Path(directory) / 'crosswire' / 'cache' / 'v1'

    def _contexts(self, base, tip, roots):
        return [[name, adapter.version,
                 adapter.fingerprint(adapter.context(Snapshot(self.repo, base, tuple(roots)))),
                 adapter.fingerprint(adapter.context(Snapshot(self.repo, tip, tuple(roots))))]
                for name, adapter in sorted(self.adapters.items())]

    def _path(self, base, tip, roots):
        key = json.dumps([_CACHE_SCHEMA, __version__, ADAPTER_API_VERSION, base, tip,
                          self._contexts(base, tip, roots)], separators=(',', ':'))
        return self.directory / (hashlib.sha256(key.encode()).hexdigest() + '.json')

    def _encode(self, summary):
        return {'schema_version': _CACHE_SCHEMA, 'adapter_api_version': ADAPTER_API_VERSION,
                'contexts': self._contexts(summary.base, summary.tip, summary.roots),
                'summaries': {item.language: self.adapters[item.language].encode_summary(item)
                              for item in summary.semantics}}

    def get(self, label, base, tip, roots):
        """Load a valid entry, returning None for absent or damaged entries."""
        try:
            data = json.loads(self._path(base, tip, roots).read_text(encoding='utf-8'))
            if (data.get('schema_version') != _CACHE_SCHEMA
                    or data.get('adapter_api_version') != ADAPTER_API_VERSION
                    or data.get('contexts') != self._contexts(base, tip, roots)
                    or not isinstance(data.get('summaries'), dict)
                    or set(data['summaries']) != set(self.adapters)):
                return None
            semantics = tuple(self.adapters[name].decode_summary(payload)
                              for name, payload in data['summaries'].items())
            summary = replace(semantics[0].legacy, semantics=semantics)
            if (summary.base, summary.tip, summary.roots) != (base, tip, tuple(roots)):
                return None
            if self._encode(summary) != data:
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
                json.dump(self._encode(summary), stream, sort_keys=True, separators=(',', ':'))
            os.replace(temporary, self._path(summary.base, summary.tip, summary.roots))
        except (OSError, ValueError, TypeError):
            pass
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
