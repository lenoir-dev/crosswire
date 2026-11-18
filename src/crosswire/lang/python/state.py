"""Conservative symbol resolution against a Git commit."""

from ...parsing import PARSE_ERRORS
import ast
import sys
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

from ... import git
from ...model import Symbol
from .analyzer import extract_symbols, _module_statements, _import_names, open_module
from ..base import Snapshot, NamespaceId, SymbolId

Status = Literal['valid', 'broken', 'unknown']


@dataclass(frozen=True, slots=True)
class Resolution:
    """Resolution status and the files consulted while determining it."""

    status: Status
    symbol: Symbol | None
    files: tuple[str, ...]
    reason: str | None = None


def _module_data(source, module, path, cache=None, blob=None, cache_identity=()):
    """Share bindings by blob and module context for the lifetime of one run."""
    key = (cache_identity, blob if blob is not None else source,
           NamespaceId('python', module), path)
    if cache is not None and key in cache:
        return cache[key]
    try:
        result = _build_module_data(source, module, path)
    except PARSE_ERRORS:
        result = None
    if cache is not None:
        cache[key] = result
    return result


def _build_module_data(source, module, path):
    """Build compact bindings and symbols for one blob."""
    try:
        tree = ast.parse(source, filename=path)
        symbols = extract_symbols(source, module, path, tree=tree)
    except PARSE_ERRORS:
        return None
    bindings = {}
    def binding(name):
        return bindings.setdefault(name, ([], []))
    for node in _module_statements(tree.body):
        if isinstance(node, ast.Import):
            for name in _import_names(node):
                binding(name)[0].append(None)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == '*':
                    continue
                name = alias.asname or alias.name
                if node.level:
                    package = module.split('.') if path.endswith('/__init__.py') or path == '__init__.py' else module.split('.')[:-1]
                    if node.level > len(package):
                        binding(name)[1].append(None)
                        continue
                    prefix = package[:len(package)-node.level+1]
                    target = '.'.join(prefix + ([node.module] if node.module else []))
                else:
                    target = node.module or ''
                binding(name)[1].append((target, alias.name) if target else None)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            binding(node.name)[0].append(symbols.get(node.name))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = {n.id for target in targets for n in ast.walk(target) if isinstance(n, ast.Name)}
            for name in names:
                binding(name)[0].append(None)
    return symbols, bindings, open_module(tree)


class StateIndex:
    """Resolve Python module bindings in a single commit."""

    def __init__(self, repo, commit, roots, data_cache=None, consulted=None, *, cache_identity=()):
        self.repo = repo
        self.commit = commit
        self.roots = tuple(roots)
        self.data_cache = data_cache if data_cache is not None else {}
        self.consulted = consulted
        self.snapshot = Snapshot(repo, commit, tuple(roots))
        self.cache_identity = cache_identity
        self._modules = {}
        self._resolutions = {}

    def _module(self, module):
        identity = NamespaceId('python', module)
        if identity in self._modules:
            return self._modules[identity]
        if not module or not all(part.isidentifier() for part in module.split('.')):
            return None
        suffix = module.replace('.', '/')
        for root in self.roots:
            for rel in (suffix + '.py', suffix + '/__init__.py'):
                path = str(PurePosixPath(root) / rel) if root not in ('', '.') else rel
                try:
                    source = self.snapshot.read(path)
                except git.SkippedBlob:
                    if self.consulted is not None:
                        self.consulted.add(path)
                    self._modules[identity] = (path, None)
                    return path, None
                if source is not None:
                    if self.consulted is not None:
                        self.consulted.add(path)
                    self._modules[identity] = (path, source)
                    return path, source
        self._modules[identity] = None
        return None

    def _data(self, source, module, path):
        entry = self.snapshot.entry(path)
        blob = entry[1] if entry else None
        return _module_data(source, module, path, self.data_cache, blob, self.cache_identity)

    def resolve(self, module: str, name: str) -> Resolution:
        """Resolve one binding, returning unknown for unresolvable external modules."""
        key = SymbolId(NamespaceId('python', module), name)
        if key not in self._resolutions:
            self._resolutions[key] = self._resolve(module, name, frozenset(), 0)
        return self._resolutions[key]

    def _resolve(self, module, name, seen, depth):
        key = SymbolId(NamespaceId('python', module), name)
        if key in seen or depth > 5:
            return Resolution('unknown', None, (), 'cycle/depth')
        item = self._module(module)
        if item is None:
            return Resolution('unknown', None, (),
                              'stdlib' if module.split('.')[0] in sys.stdlib_module_names else 'third-party')
        path, source = item
        if source is None:
            return Resolution('unknown', None, (path,), 'skipped-blob')
        data = self._data(source, module, path)
        if data is None:
            return Resolution('unknown', None, (path,), 'parse-failure')
        symbols, bindings, is_open = data
        if name not in symbols:
            if path.endswith('/__init__.py') or path == '__init__.py':
                submodule = self._module(f'{module}.{name}')
                if submodule is not None:
                    if submodule[1] is None:
                        return Resolution('unknown', None, (path, submodule[0]), 'skipped-blob')
                    return Resolution('valid', None, (path, submodule[0]))
            if is_open:
                return Resolution('unknown', None, (path,), 'open-module')
            return Resolution('broken', None, (path,))
        concrete, imports = bindings.get(name, ((), ()))
        if concrete:
            symbol = concrete[-1]
            if symbol is not None and (symbol.kind not in ('function', 'class') or symbol.params is None):
                symbol = None
            return Resolution('valid', symbol, (path,))
        files = [path]
        statuses = []
        reasons = []
        for target in imports:
            if target is None:
                statuses.append('unknown')
                reasons.append('unsupported-import')
                continue
            submodule = self._module('.'.join(target))
            if submodule is not None:
                files.append(submodule[0])
                if submodule[1] is not None:
                    return Resolution('valid', None, tuple(dict.fromkeys(files)))
                statuses.append('unknown')
                reasons.append('skipped-blob')
                continue
            result = self._resolve(*target, seen | {key}, depth + 1)
            files.extend(result.files)
            statuses.append(result.status)
            reasons.append(result.reason)
            if result.status == 'valid':
                return Resolution('valid', result.symbol, tuple(dict.fromkeys(files)))
        status = 'unknown' if 'unknown' in statuses else 'broken'
        reason = next((reason for reason in reasons if reason), None)
        return Resolution(status, None, tuple(dict.fromkeys(files)), reason)

    def is_open(self, module):
        """Return whether a module has exports that static analysis cannot close."""
        item = self._module(module)
        if item is None or item[1] is None:
            return False
        data = self._data(item[1], module, item[0])
        return data is not None and data[2]
