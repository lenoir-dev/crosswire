import ast
from pathlib import PurePosixPath
from dataclasses import replace
from .model import CallShape, Param, Reference, Symbol


def module_name_for_path(path, roots):
    """Module name for path."""
    p = PurePosixPath(path)
    if p.suffix != '.py':
        return None
    for root in roots:
        r = PurePosixPath(root)
        try:
            rel = p.relative_to(r) if root not in ('', '.') else p
        except ValueError:
            continue
        parts = list(rel.parts)
        parts[-1] = parts[-1][:-3]
        if parts[-1] == '__init__':
            parts.pop()
        return '.'.join(parts) if parts and all(x.isidentifier()
                                                for x in parts) else None
    return None


def _params(args):
    pos = [*args.posonlyargs, *args.args]
    first_default = len(pos) - len(args.defaults)
    out = [
        Param(
            a.arg,
            'posonly' if i < len(
                args.posonlyargs) else 'pos',
            i >= first_default) for i,
        a in enumerate(pos)]
    if args.vararg:
        out.append(Param(args.vararg.arg, 'vararg', False))
    out += [Param(a.arg, 'kwonly', default is not None)
            for a, default in zip(args.kwonlyargs, args.kw_defaults)]
    if args.kwarg:
        out.append(Param(args.kwarg.arg, 'varkw', False))
    return tuple(out)


def _shape(kind, params):
    return repr((kind, tuple((p.name, p.kind)
                for p in params) if params is not None else None))


def _target_names(node):
    if isinstance(node, ast.Name):
        yield node.id
    elif isinstance(node, (ast.Tuple, ast.List)):
        for e in node.elts:
            yield from _target_names(e)


def _module_statements(body):
    """Yield definitions in module scope, including guarded suites, in source order."""
    for node in body:
        if isinstance(node, ast.If):
            yield from _module_statements(node.body)
            yield from _module_statements(node.orelse)
        elif isinstance(node, (ast.Try, ast.TryStar)):
            yield from _module_statements(node.body)
            for handler in node.handlers:
                yield from _module_statements(handler.body)
            yield from _module_statements(node.orelse)
            yield from _module_statements(node.finalbody)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            yield from _module_statements(node.body)
        else:
            yield node


def _import_names(node):
    if isinstance(node, ast.ImportFrom):
        return [a.asname or a.name for a in node.names if a.name != '*']
    if isinstance(node, ast.Import):
        return [a.asname or a.name.split('.')[0] for a in node.names]
    return []


def extract_symbols(source, module, path):
    """Extract symbols."""
    tree = ast.parse(source, filename=path)
    out = {}
    counts = {}

    def add(name, kind, node, params=None):
        """Add."""
        counts[name] = counts.get(name, 0) + 1
        out[name] = Symbol(
            module,
            name,
            kind,
            path,
            node.lineno,
            params,
            _shape(
                kind,
                params))
    for node in _module_statements(tree.body):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            add(node.name, 'function', node,
                None if node.decorator_list else _params(node.args))
        elif isinstance(node, ast.ClassDef):
            # A later class definition replaces methods from an earlier class.
            for key in list(out):
                if key.startswith(node.name + '.'):
                    del out[key]
            init = next(
                (x for x in reversed(
                    node.body) if isinstance(
                    x,
                    (ast.FunctionDef,
                     ast.AsyncFunctionDef)) and x.name == '__init__'),
                None)
            simple = not node.decorator_list and not node.keywords and all(
                isinstance(b, ast.Name) and b.id == 'object' for b in node.bases)
            params = _params(
                init.args)[
                1:] if simple and init and not init.decorator_list and (
                init.args.posonlyargs or init.args.args) else None
            add(node.name, 'class', node, params)
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    add(node.name + '.' + child.name, 'method', child)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(
                node, ast.Assign) else [node.target]
            for target in targets:
                for name in _target_names(target):
                    add(name, 'variable', node)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for name in _import_names(node):
                add(name, 'variable', node)
    for name, count in counts.items():
        if count > 1:
            symbol = out[name]
            out[name] = replace(
                symbol, params=None, shape=_shape(
                    symbol.kind, None))
    return out


def definition_dumps(source):
    """Definition dumps."""
    tree = ast.parse(source)
    out = {}
    for node in _module_statements(tree.body):
        if isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out[node.name] = ast.dump(node, include_attributes=False)
            if isinstance(node, ast.ClassDef):
                for key in list(out):
                    if key.startswith(node.name + '.'):
                        del out[key]
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef,
                                  ast.AsyncFunctionDef)):
                        out[node.name + '.' +
                            child.name] = ast.dump(child, include_attributes=False)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            for target in node.targets if isinstance(
                    node, ast.Assign) else [node.target]:
                for name in _target_names(target):
                    out[name] = ast.dump(node, include_attributes=False)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for name in _import_names(node):
                out[name] = ast.dump(node, include_attributes=False)
    return out


def extract_references(source, module, path, is_package):
    """Extract references."""
    tree = ast.parse(source, filename=path)
    bindings = {}
    imports = []
    shadow = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                package = module.split(
                    '.') if is_package else module.split('.')[:-1]
                if node.level > len(package):
                    continue
                prefix = package[:len(package) - node.level + 1]
                target = '.'.join(prefix +
                                  ([node.module] if node.module else []))
            else:
                target = node.module or ''
            if not target or target == 'importlib':
                continue
            for a in node.names:
                if a.name == '*':
                    continue
                local = a.asname or a.name
                bindings[local] = ('symbol', target, a.name)
                imports.append((local, node.lineno, target, a.name))
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name == 'importlib' or a.name.startswith('importlib.'):
                    continue
                # Without an alias Python binds the first component, not the
                # whole dotted module.
                local = a.asname or a.name.split('.')[0]
                target = a.name if a.asname else a.name.split('.')[0]
                bindings[local] = ('module', target, '')
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            shadow.add(node.id)
        elif isinstance(node, ast.arg):
            shadow.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            shadow.add(node.name)
    for name in shadow:
        bindings.pop(name, None)
    result = [
        Reference(
            path,
            line,
            target,
            name,
            None) for local,
        line,
        target,
        name in imports if bindings.get(local) == (
            'symbol',
            target,
            name)]

    def target(node):
        """Target."""
        if isinstance(node, ast.Name):
            b = bindings.get(node.id)
            if b and b[0] == 'symbol':
                return b[1], b[2]
        if isinstance(node, ast.Attribute) and isinstance(
                node.value, ast.Name):
            b = bindings.get(node.value.id)
            if b and b[0] == 'module':
                return b[1], node.attr
        return None

    class Visitor(ast.NodeVisitor):
        def visit_Call(self, node):
            """Visit call."""
            t = target(node.func)
            if t:
                shape = CallShape(
                    sum(
                        not isinstance(
                            a, ast.Starred) for a in node.args), tuple(
                        k.arg for k in node.keywords if k.arg is not None), any(
                        isinstance(
                            a, ast.Starred) for a in node.args), any(
                            k.arg is None for k in node.keywords))
                result.append(Reference(path, node.lineno, *t, shape))
            else:
                self.visit(node.func)
            for arg in node.args:
                self.visit(arg)
            for kw in node.keywords:
                self.visit(kw.value)

        def visit_Attribute(self, node):
            """Visit attribute."""
            t = target(node)
            if t:
                result.append(Reference(path, node.lineno, *t, None))
            else:
                self.generic_visit(node)

        def visit_Name(self, node):
            """Visit name."""
            if isinstance(node.ctx, ast.Load):
                t = target(node)
                if t:
                    result.append(Reference(path, node.lineno, *t, None))
    Visitor().visit(tree)
    return result
