"""Caller AST identities for pinned checker diagnostics; never parse prose."""
import ast
from collections import defaultdict
import hashlib
import json
from pathlib import PurePosixPath

from .m3 import Identity, Observation


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":")).encode()).hexdigest()


def module_of(path):
    parts=list(PurePosixPath(path).with_suffix("").parts)
    if parts and parts[0] in {"src","lib"}:parts.pop(0)
    if parts and parts[-1]=="__init__":parts.pop()
    return ".".join(parts)


def identify_files(files, errors, *, known_modules, files_analyzed, environment_failure=False):
    complete=files_analyzed==len(files) and bool(files)
    trees={};parents={};ambiguous=False;identities=[];supported=[]
    for path,source in files.items():
        try:trees[path]=ast.parse(source)
        except (SyntaxError,ValueError,RecursionError):complete=False
    def scope(node,parent_map):
        names=[]
        while node in parent_map:
            node=parent_map[node]
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):names.append(node.name)
        return ".".join(reversed(names))
    for path,tree in trees.items():parents[path]={child:node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    for error in errors:
        path=error.get("file");rule=error.get("rule")
        if path not in trees or not isinstance(rule,str):identities.append(None);continue
        tree=trees[path];parent_map=parents[path];module=module_of(path)
        line=error["range"]["start"]["line"]+1;column=error["range"]["start"]["character"]
        imports={};import_nodes=[];alias_targets=defaultdict(set)
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):
                import_nodes.append(node)
                imports.update({a.asname or a.name.split('.')[0]:a.name for a in node.names})
                for a in node.names:alias_targets[a.asname or a.name.split('.')[0]].add(a.name)
            elif isinstance(node,ast.ImportFrom):
                import_nodes.append(node)
                package=module if path.endswith('/__init__.py') or path=='__init__.py' else module.rpartition('.')[0]
                base=node.module or ""
                if node.level:
                    parts=package.split('.') if package else []
                    base='.'.join([*parts[:len(parts)-node.level+1],*([base] if base else [])])
                imports.update({a.asname or a.name:base+'.'+a.name for a in node.names if a.name!='*'})
                for a in node.names:
                    if a.name!='*':alias_targets[a.asname or a.name].add(base+'.'+a.name)
        def covers(node):
            start=(node.lineno,node.col_offset);end=(getattr(node,'end_lineno',node.lineno),getattr(node,'end_col_offset',node.col_offset+1))
            return start <= (line,column) < end
        candidates=[n for n in ast.walk(tree) if isinstance(n,(ast.Call,ast.Attribute,ast.Import,ast.ImportFrom)) and covers(n)]
        if rule=='reportMissingImports':
            candidates=[n for n in import_nodes if covers(n)]
        if not candidates:
            candidates=[n for n in ast.walk(tree) if isinstance(n,ast.expr) and hasattr(n,'lineno') and covers(n)]
        if not candidates:identities.append(None);continue
        # Attribute errors point at a selector; call errors use its enclosing
        # call so changing arguments cannot be subtracted from an old error.
        if rule=='reportCallIssue':
            calls=[n for n in candidates if isinstance(n,ast.Call)]
            if calls:candidates=calls
        node=min(candidates,key=lambda n:len(ast.dump(n,include_attributes=False)))
        owner=scope(node,parent_map);symbol=None;first_party=False;shadowed=False
        if rule=='reportMissingImports':
            if isinstance(node,ast.Import):names=[a.name for a in node.names]
            elif isinstance(node,ast.ImportFrom):
                alias=next((a for a in node.names if a.name!='*'),None)
                name=imports.get(alias.asname or alias.name,'') if alias else ''
                names=[name.rpartition('.')[0]]
            else:names=[]
            if len(names)!=1:identities.append(None);continue
            symbol=names[0]
            first_party=symbol in known_modules or any(m.startswith(symbol+'.') for m in known_modules)
            if not first_party:environment_failure=True
        else:
            expression=node.func if isinstance(node,ast.Call) else node
            if isinstance(expression,(ast.Import,ast.ImportFrom)):
                if len(expression.names)!=1:identities.append(None);continue
                alias=expression.names[0];symbol=imports.get(alias.asname or alias.name)
            else:
                spelling=ast.unparse(expression);head,sep,tail=spelling.partition('.')
                if len(alias_targets.get(head,()))>1:shadowed=True
                if head in imports and any((isinstance(n,ast.Name) and isinstance(n.ctx,ast.Store) and n.id==head
                    or isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and n.name==head)
                    and scope(n,parent_map)==owner for n in ast.walk(tree)):shadowed=True
                ancestor=node
                while ancestor in parent_map:
                    ancestor=parent_map[ancestor]
                    if isinstance(ancestor,(ast.FunctionDef,ast.AsyncFunctionDef)):
                        if any(arg.arg==head for arg in ast.walk(ancestor.args) if isinstance(arg,ast.arg)):shadowed=True
                        if head in imports and any(isinstance(n,ast.Name) and isinstance(n.ctx,ast.Store) and n.id==head for n in ast.walk(ancestor)):shadowed=True
                if head in imports:symbol=imports[head]+('.'+tail if sep else '')
                else:symbol='.'.join(x for x in (module,owner,spelling) if x)
            first_party=any(symbol==m or symbol.startswith(m+'.') for m in known_modules) if symbol else False
        if not symbol:identities.append(None);continue
        if shadowed:ambiguous=True
        expression_key=ast.dump(node,include_attributes=False)
        same=[n for n in ast.walk(tree) if type(n) is type(node) and ast.dump(n,include_attributes=False)==expression_key and scope(n,parent_map)==owner]
        if len(same)!=1:ambiguous=True
        occurrence=fingerprint((owner,expression_key))
        target_module=max((m for m in known_modules if symbol.startswith(m+'.')),key=len,default=None)
        name=symbol[len(target_module)+1:] if target_module else ''
        target_tree=trees.get(known_modules.get(target_module,''))
        declarations=[n for n in target_tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and n.name==name] if target_tree else []
        if declarations:
            context=[ast.dump(n,include_attributes=False) for n in declarations]
        elif rule in {'reportMissingImports','reportAttributeAccessIssue'} and first_party and (rule=='reportMissingImports' or '.' not in name):
            context=['missing-binding',symbol]
        else:
            enclosing=node
            while enclosing in parent_map and not isinstance(enclosing,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
                enclosing=parent_map[enclosing]
            context=ast.dump(enclosing,include_attributes=False)
        root=fingerprint((rule,symbol,owner,context))
        identity=Identity(rule,path,symbol,occurrence,root)
        identities.append(identity)
        if rule=='reportMissingImports' and first_party:supported.append(identity)
        elif rule in {'reportCallIssue','reportAttributeAccessIssue'} and first_party and not shadowed:
            # Only resolved first-party module-level functions/classes/bindings
            # are supported. Value methods and decorated/splatted calls are not.
            simple_name='.' not in name
            no_star=not isinstance(node,ast.Call) or not any(isinstance(a,ast.Starred) for a in node.args) and not any(k.arg is None for k in node.keywords)
            if simple_name and no_star and (rule=='reportAttributeAccessIssue' or declarations and not any(n.decorator_list for n in declarations)):
                supported.append(identity)
    return Observation(tuple(identities),complete=complete,environment_failure=environment_failure,
                       ambiguous=ambiguous,supported=tuple(supported))
