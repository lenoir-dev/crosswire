"""Conservative symbol resolution against a Git commit."""

import ast
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


class StateIndex:
    """Resolve Python module bindings in a single commit."""

    def __init__(self, repo, commit, roots):
        self.repo = repo
        self.commit = commit
        self.roots = tuple(roots)
        self._modules = {}

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
        return self._resolve(module, name, frozenset(), 0)

    def _resolve(self, module, name, seen, depth):
        key = (module, name)
        if key in seen or depth > 5:
            return Resolution('unknown', None, ())
        item = self._module(module)
        if item is None:
            return Resolution('unknown', None, ())
        path, source = item
        try:
            tree = ast.parse(source, filename=path)
            symbols = extract_symbols(source, module, path)
        except SyntaxError:
            return Resolution('unknown', None, (path,))
        if name not in symbols:
            return Resolution('broken', None, (path,))
        concrete = []
        imports = []
        for node in _module_statements(tree.body):
            if isinstance(node, (ast.Import, ast.ImportFrom)) and name in _import_names(node):
                if isinstance(node, ast.Import):
                    concrete.append(None)
                else:
                    for alias in node.names:
                        if alias.name == '*' or (alias.asname or alias.name) != name:
                            continue
                        if node.level:
                            package = module.split('.') if path.endswith('/__init__.py') or path == '__init__.py' else module.split('.')[:-1]
                            if node.level > len(package):
                                imports.append(None)
                                continue
                            prefix = package[:len(package)-node.level+1]
                            target = '.'.join(prefix + ([node.module] if node.module else []))
                        else:
                            target = node.module or ''
                        imports.append((target, alias.name) if target else None)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name:
                concrete.append(symbols.get(name))
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(isinstance(n, ast.Name) and n.id == name for t in targets for n in ast.walk(t)):
                    concrete.append(None)
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
