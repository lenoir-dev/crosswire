"""Collect deterministic coverage gaps from user-visible Git states."""

import ast
from functools import lru_cache

from . import git
from .parsing import PARSE_ERRORS
from .python_analyzer import cached_references, module_name_for_path, open_module


@lru_cache(maxsize=16384)
def _sites(source, module, path):
    """Extract state-independent gaps and references once for each source blob."""
    gaps = []
    try:
        tree = ast.parse(source)
        refs = cached_references(source, module, path, path.endswith('/__init__.py')) if module else ()
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


def inspect(repo, commits, roots=None, analysis=None):
    """Count distinct (path, line, construct) sites, excluding internal trials."""
    if analysis is None:
        return {}
    sites = {}
    requested = set(commits)

    def add(category, path, line, construct):
        sites.setdefault(category, set()).add((path, line, construct))

    contexts = set(analysis.observed) | set(analysis.consulted) | set(analysis.candidates) | set(analysis.changed)
    for commit, source_roots in sorted(contexts):
        if commit not in requested:
            continue
        index = analysis.index(commit, source_roots)
        refs = analysis.observed.get((commit, source_roots), ())
        # Resolve only references that participated in this run. External modules
        # are outside the supported analysis, rather than evidence of a gap.
        unresolved = []
        for ref in sorted(refs, key=lambda r: (r.path, r.line, r.module, r.name, repr(r.call))):
            result = index.resolve(ref.module, ref.name)
            if result.status == 'unknown' and result.reason not in ('third-party', 'stdlib'):
                unresolved.append((ref, result.reason or 'unsupported'))
        paths = (analysis.changed.get((commit, source_roots), set())
                 | analysis.consulted.get((commit, source_roots), set())
                 | analysis.candidates.get((commit, source_roots), set())
                 | {ref.path for ref in refs})
        entries = git.entries_for_paths(repo, commit, paths)
        file_refs = {}
        for path in sorted(paths):
            entry = entries.get(path)
            if entry is None:
                continue
            if entry[0] == '160000':
                add('submodule', path, 1, 'submodule not analyzed')
                continue
            if path.endswith('.pyi'):
                if path in analysis.changed_paths:
                    add('unsupported', path, 1, 'stub file')
                continue
            if not path.endswith('.py'):
                continue
            try:
                source = git.read_blob(repo, entry[1])
            except git.SkippedBlob as exc:
                add(exc.reason, path, 1, exc.reason)
                continue
            if source is None:
                continue
            module = module_name_for_path(path, source_roots)
            gaps, present_refs = _sites(source, module, path)
            file_refs[path] = present_refs
            for category, line, construct in gaps:
                if category not in ('parse_failure', 'non_utf8') and path not in analysis.changed_paths:
                    continue
                add(category, path, line, construct)
                if category == 'parse_failure':
                    analysis.warn_parse(path, commit)
        for ref, reason in unresolved:
            matches = [present for present in file_refs.get(ref.path, ())
                       if (present.module, present.name, present.call) == (ref.module, ref.name, ref.call)]
            if not matches:
                continue
            line = min(matches, key=lambda present: (abs(present.line - ref.line), present.line)).line
            add(f'unknown_resolution:{reason}', ref.path, line, f'{ref.module}.{ref.name}')
    return {category: {'count': len(items), 'examples': [f'{p}:{line}: {kind}' for p, line, kind in sorted(items)[:5]]}
            for category, items in sorted(sites.items())}


def text_lines(coverage, limitations, limits=None):
    """Render coverage and every category, including gaps alongside search bounds."""
    lines = []
    if coverage == 'bounded':
        lines.append(f"Coverage: bounded ({', '.join((limits or {}).get('hit', ()))}) — unchecked combinations are not proven safe.")
    elif coverage == 'partial':
        lines.append('Coverage: partial — some sites could not be analyzed.')
    for category, detail in sorted((limitations or {}).items()):
        lines.append(f"Limitation: {category}: {detail['count']} site(s)" +
                     (f" ({'; '.join(detail['examples'])})" if detail['examples'] else ''))
    return lines
