"""Conservative symbol resolution against a Git commit."""

import ast
import hashlib
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

from . import git
from .model import Symbol
from .python_analyzer import extract_symbols, _module_statements, _import_names

Status = Literal['valid', 'broken', 'unknown']


@dataclass(frozen=True, slots=True)
class Resolution:
    """Resolution status and the files consulted while determining it."""

    status: Status
    symbol: Symbol | None
    files: tuple[str, ...]


_data_cache = OrderedDict()
_data_lock = threading.RLock()


def _module_data(source, module, path):
    """Share compact bindings by content hash and module resolution context."""
    key = (hashlib.sha256(source.encode('utf-8')).digest(), module, path)
    with _data_lock:
        if key in _data_cache:
            _data_cache.move_to_end(key)
            return _data_cache[key]
        result = _build_module_data(source, module, path)
        _data_cache[key] = result
        if len(_data_cache) > 8192:
            _data_cache.popitem(last=False)
        return result


def _build_module_data(source, module, path):
    """Build compact bindings and symbols for one blob."""
    try:
        tree = ast.parse(source, filename=path)
        symbols = extract_symbols(source, module, path, tree=tree)
    except SyntaxError:
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
    return symbols, bindings


class StateIndex:
    """Resolve Python module bindings in a single commit."""

    def __init__(self, repo, commit, roots):
        self.repo = repo
        self.commit = commit
        self.roots = tuple(roots)
        self._modules = {}
        self._resolutions = {}

    def _module(self, module):
        if module in self._modules:
            return self._modules[module]
        if not module or not all(part.isidentifier() for part in module.split('.')):
            return None
        suffix = module.replace('.', '/')
        for root in self.roots:
            for rel in (suffix + '.py', suffix + '/__init__.py'):
                path = str(PurePosixPath(root) / rel) if root not in ('', '.') else rel
                source = git.read_file(self.repo, self.commit, path)
                if source is not None:
                    self._modules[module] = (path, source)
                    return path, source
        self._modules[module] = None
        return None

    def resolve(self, module: str, name: str) -> Resolution:
        """Resolve one binding, returning unknown for unresolvable external modules."""
        key = (module, name)
        if key not in self._resolutions:
            self._resolutions[key] = self._resolve(module, name, frozenset(), 0)
        return self._resolutions[key]

    def _resolve(self, module, name, seen, depth):
        key = (module, name)
        if key in seen or depth > 5:
            return Resolution('unknown', None, ())
        item = self._module(module)
        if item is None:
            return Resolution('unknown', None, ())
        path, source = item
        data = _module_data(source, module, path)
        if data is None:
            return Resolution('unknown', None, (path,))
        symbols, bindings = data
        if name not in symbols:
            return Resolution('broken', None, (path,))
        concrete, imports = bindings.get(name, ((), ()))
        if concrete:
            symbol = concrete[-1]
            if symbol is not None and (symbol.kind not in ('function', 'class') or symbol.params is None):
                symbol = None
            return Resolution('valid', symbol, (path,))
        files = [path]
        statuses = []
        for target in imports:
            if target is None:
                statuses.append('unknown')
                continue
            result = self._resolve(*target, seen | {key}, depth + 1)
            files.extend(result.files)
            statuses.append(result.status)
            if result.status == 'valid':
                return Resolution('valid', result.symbol, tuple(dict.fromkeys(files)))
        status = 'unknown' if 'unknown' in statuses else 'broken'
        return Resolution(status, None, tuple(dict.fromkeys(files)))
