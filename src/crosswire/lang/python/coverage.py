"""Python-only unsupported-site extraction."""

import ast
from functools import lru_cache
from ...parsing import PARSE_ERRORS
from .analyzer import cached_references, open_module


@lru_cache(maxsize=16384)
def _sites(source, module, path, cache_identity=(1, 'python', '1')):
    """Extract state-independent gaps and references once for each source blob."""
    gaps = []
    try:
        tree = ast.parse(source)
        refs = cached_references(source, module, path, path.endswith('/__init__.py'),
                                 cache_identity=cache_identity) if module else ()
        if open_module(tree):
            gaps.append(('open-module', 1, 'open module exports'))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and any(x.name == '*' for x in node.names):
                gaps.append(('unsupported', node.lineno, 'star import'))
            elif isinstance(node, ast.If):
                guard = ast.unparse(node.test)
                construct = 'type-only import' if 'TYPE_CHECKING' in guard else 'conditional import'
                for child in ast.walk(node):
                    if isinstance(child, (ast.Import, ast.ImportFrom)):
                        gaps.append(('unsupported', child.lineno, construct))
            elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, (ast.Attribute, ast.Subscript)):
                        gaps.append(('unsupported', node.lineno, 'runtime attribute or item mutation'))
            elif isinstance(node, ast.Call):
                if any(isinstance(a, ast.Starred) for a in node.args) or any(k.arg is None for k in node.keywords):
                    gaps.append(('splatted_call', node.lineno, 'splatted call'))
                if isinstance(node.func, ast.Name) and node.func.id in ('getattr', '__import__'):
                    gaps.append(('unsupported', node.lineno, node.func.id))
                elif (isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                      and node.func.value.id == 'importlib'):
                    gaps.append(('unsupported', node.lineno, 'importlib'))
                elif isinstance(node.func, ast.Attribute):
                    # Imported module attributes are handled by the reference resolver.
                    if not any(ref.line == node.lineno and ref.call is not None for ref in refs):
                        gaps.append(('unsupported', node.lineno, 'method or dynamic call'))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.decorator_list:
                gaps.append(('unsupported', node.lineno, 'decorated definition'))
        return tuple(gaps), refs
    except PARSE_ERRORS:
        return (('parse_failure', 1, 'parse failure'),), ()

