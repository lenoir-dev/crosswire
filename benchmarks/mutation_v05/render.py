"""Seeded real-declaration mutations, independently rendered before any labels."""
import ast
from copy import deepcopy
import hashlib
from pathlib import PurePosixPath
import re
import tokenize
import io

from benchmarks.s17.identity import module_of

GAP='\n'+''.join(f'# mutation integration separator {n:02d}\n' for n in range(20))
TESTS={'tests','test','_tests','testing','testsuite'}


def tree(source):return ast.parse(source)


def select_sites(files,spec,seed):
    choices=[]
    for path,source in sorted(files.items()):
        if not path.endswith('.py') or any(p in TESTS for p in PurePosixPath(path).parts):continue
        if not any(path==r or path.startswith(r+'/') for r in spec['roots']):continue
        try:t=tree(source)
        except SyntaxError:continue
        module=module_of(path)
        choices.append(dict(kind='module',path=path,name=module,module=module,line=0))
        for node in t.body:
            if not isinstance(node,(ast.FunctionDef,ast.ClassDef)) or node.name.startswith('_') or node.decorator_list:continue
            if sum(isinstance(n,type(node)) and n.name==node.name for n in t.body)!=1:continue
            if any(isinstance(n,ast.arg) and n.arg==node.name for n in ast.walk(t)):continue
            signature=node if isinstance(node,ast.FunctionDef) else next((n for n in node.body if isinstance(n,ast.FunctionDef) and n.name=='__init__'),None)
            if signature and (signature.args.vararg or signature.args.kwarg or signature.decorator_list):continue
            choices.append(dict(kind='function' if isinstance(node,ast.FunctionDef) else 'class',path=path,
                                name=node.name,module=module,line=node.lineno))
    for item in choices:
        key='|'.join([seed,spec['url'],spec['sha'],item['kind'],item['path'],item['name']])
        item['rank_sha256']=hashlib.sha256(key.encode()).hexdigest()
    result=[]
    for kind in ('function','class','module'):
        candidates=sorted((c for c in choices if c['kind']==kind),key=lambda c:(c['rank_sha256'],c['path'],c['name']))
        if candidates:result.append(candidates[0])
    return result


def offset(source,line,column):
    lines=source.splitlines(keepends=True)
    return sum(map(len,lines[:line-1]))+len(lines[line-1].encode()[:column].decode())


def span(source,node):
    return offset(source,node.lineno,node.col_offset),offset(source,node.end_lineno,node.end_col_offset)


def edits(source,changes):
    # Multiple zero-width call-argument insertions are permitted; overlapping
    # replacements are not guessed and become a structural render exclusion.
    changes=sorted(set(changes),reverse=True);last=len(source)+1
    for start,end,value in changes:
        if end>last:raise ValueError('overlapping source edits')
        source=source[:start]+value+source[end:];last=start
    ast.parse(source)
    return source


def absolute_from(path,node):
    if not node.level:return node.module or ''
    module=module_of(path);package=module if path.endswith('__init__.py') else module.rpartition('.')[0]
    pieces=package.split('.') if package else []
    return '.'.join([*pieces[:len(pieces)-node.level+1],*([node.module] if node.module else [])])


def bindings(path,t):
    result={}
    for n in ast.walk(t):
        if isinstance(n,ast.Import):
            result.update({a.asname or a.name.split('.')[0]:a.name if a.asname else a.name.split('.')[0] for a in n.names})
        elif isinstance(n,ast.ImportFrom):
            result.update({a.asname or a.name:absolute_from(path,n)+'.'+a.name for a in n.names if a.name!='*'})
    return result


def exports(files):
    result={}
    for path,source in files.items():
        if not path.endswith('.py'):continue
        for n in tree(source).body:
            if isinstance(n,ast.ImportFrom):
                for a in n.names:
                    if a.name!='*':result[module_of(path)+'.'+(a.asname or a.name)]=absolute_from(path,n)+'.'+a.name
    return result


def resolved(expression,path,names,forward):
    spelling=ast.unparse(expression);head,sep,tail=spelling.partition('.')
    value=names.get(head,module_of(path)+'.'+head)+('.'+tail if sep else '')
    for _ in range(5):
        if value not in forward:break
        value=forward[value]
    return value


def declaration(source,site):
    return next(n for n in tree(source).body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name==site['name'])


def renamed(files,site,new):
    result=dict(files);old=site['name']
    for path,source in files.items():
        if not path.endswith('.py'):continue
        t=tree(source);names=bindings(path,t);changes=[]
        annotations=set()
        for parent in ast.walk(t):
            annotation=parent.annotation if isinstance(parent,(ast.arg,ast.AnnAssign)) else parent.returns if isinstance(parent,(ast.FunctionDef,ast.AsyncFunctionDef)) else None
            if annotation is not None:annotations.update(ast.walk(annotation))
        for n in ast.walk(t):
            if isinstance(n,ast.ImportFrom) and absolute_from(path,n)==site['module'] and any(a.name==old for a in n.names):
                replacement=deepcopy(n)
                for a in replacement.names:
                    if a.name==old:a.asname=a.asname or old;a.name=new
                changes.append((*span(source,n),ast.unparse(replacement)))
            elif isinstance(n,ast.Attribute) and n.attr==old:
                prefix=resolved(n.value,path,names,{})
                if prefix==site['module']:changes.append((*span(source,n),ast.unparse(n.value)+'.'+new))
            elif path==site['path'] and isinstance(n,ast.Name) and n.id==old:
                changes.append((*span(source,n),new))
            elif path==site['path'] and isinstance(n,ast.Constant) and isinstance(n.value,str) and n in annotations:
                changed=re.sub(r'\b'+re.escape(old)+r'\b',new,n.value)
                if changed!=n.value:changes.append((*span(source,n),repr(changed)))
            elif path==site['path'] and isinstance(n,ast.Assign) and any(isinstance(a,ast.Name) and a.id=='__all__' for a in n.targets):
                for value in ast.walk(n.value):
                    if isinstance(value,ast.Constant) and value.value==old:changes.append((*span(source,value),repr(new)))
        if path==site['path']:
            n=declaration(source,site);lines=source.splitlines(keepends=True);line=lines[n.lineno-1]
            match=re.search(r'\b(?:def|class)\s+('+re.escape(old)+r')\b',line)
            start=sum(map(len,lines[:n.lineno-1]))+match.start(1)
            changes.append((start,start+len(old),new))
        if changes:result[path]=edits(source,changes)
    return result


def arity(files,site,optional=False):
    result=dict(files);forward=exports(files);target=site['module']+'.'+site['name']
    for path,source in files.items():
        if not path.endswith('.py'):continue
        t=tree(source);names=bindings(path,t);changes=[]
        for n in ast.walk(t):
            if isinstance(n,ast.Call) and resolved(n.func,path,names,forward)==target:
                end=span(source,n)[1]-1
                changes.append((end,end,(', ' if n.args or n.keywords else '')+'_mutation_required=None'))
        if path==site['path']:
            n=declaration(source,site);args=deepcopy(n.args)
            args.kwonlyargs.append(ast.arg(arg='_mutation_required',annotation=ast.Name(id='object',ctx=ast.Load())))
            args.kw_defaults.append(ast.Constant(None) if optional else None)
            tokens=list(tokenize.generate_tokens(io.StringIO(source).readline));depth=0;start=None
            for tok in tokens:
                if tok.start[0]<n.lineno:continue
                if tok.string=='(':
                    if start is None:start=sum(len(x) for x in source.splitlines(keepends=True)[:tok.start[0]-1])+tok.start[1]+1
                    depth+=1
                elif tok.string==')' and start is not None:
                    depth-=1
                    if not depth:
                        end=sum(len(x) for x in source.splitlines(keepends=True)[:tok.start[0]-1])+tok.start[1]
                        changes.append((start,end,ast.unparse(args)));break
        if changes:result[path]=edits(source,changes)
    return result


def backup(site):
    path=PurePosixPath(site['path']);new=path.with_name(path.stem+'_mutation_backup.py').as_posix()
    return new,module_of(new)


def consumer(files,site,name=None,unrelated=False):
    if unrelated:return 'from pathlib import PurePath\nPurePath("mutation-example.txt")\n'
    if site['kind']=='module':
        candidates=[]
        def exported(nodes):
            for node in nodes:
                if isinstance(node,(ast.FunctionDef,ast.ClassDef)):
                    candidates.append(node.name)
                elif isinstance(node,ast.ImportFrom):candidates.extend(a.asname or a.name for a in node.names if a.name!='*')
                elif isinstance(node,(ast.Assign,ast.AnnAssign)):
                    candidates.extend(n.id for n in ast.walk(node) if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Store))
                elif isinstance(node,(ast.If,ast.Try)):
                    exported(node.body);exported(node.orelse)
                    if isinstance(node,ast.Try):
                        for handler in node.handlers:exported(handler.body)
        exported(tree(files[site['path']]).body)
        candidates.sort(key=lambda x:(x.startswith('_'),x))
        member=candidates[0] if candidates else '__name__'
        return f"import {name or site['module']} as api\napi.{member}\n"
    if site['kind']=='class':
        # Registration/reference use tests the real class binding without
        # inventing constructor values for inherited/NamedTuple constructors.
        return f"import {site['module']} as api\napi.{name or site['name']}\n"
    node=declaration(files[site['path']],site);signature=node if isinstance(node,ast.FunctionDef) else next((n for n in node.body if isinstance(n,ast.FunctionDef) and n.name=='__init__'),None)
    arguments=[];keywords=[]
    if signature:
        a=signature.args;pos=[*a.posonlyargs,*a.args]
        required=pos[:len(pos)-len(a.defaults)]
        if isinstance(node,ast.ClassDef):required=required[1:]
        arguments=[f'argument_{i}' for i in range(len(required))]
        for arg,default in zip(a.kwonlyargs,a.kw_defaults):
            if default is None:keywords.append(arg.arg+'=argument_'+str(len(arguments)+len(keywords)))
    count=len(arguments)+len(keywords)
    return ('from typing import Any\n'+f"import {site['module']} as api\n"+
            ''.join(f'argument_{i}: Any = None\n' for i in range(count))+
            f"api.{name or site['name']}({', '.join([*arguments,*keywords])})\n")


def move(files,site,copy_only=False):
    old=site['module'];new=old+'_mutated';path=PurePosixPath(site['path'])
    package=path.name=='__init__.py';oldpath=path.parent.as_posix() if package else site['path']
    newpath=path.parent.with_name(path.parent.name+'_mutated').as_posix() if package else path.with_name(path.stem+'_mutated.py').as_posix()
    result=dict(files)
    for relative,source in files.items():
        if not relative.endswith('.py'):continue
        t=tree(source);changes=[];parents={c:n for n in ast.walk(t) for c in ast.iter_child_nodes(n)}
        for n in ast.walk(t):
            if isinstance(n,ast.Import):
                replacement=deepcopy(n)
                for a in replacement.names:
                    if a.name==old or a.name.startswith(old+'.'):a.name=new+a.name[len(old):]
                if ast.dump(replacement)!=ast.dump(n):changes.append((*span(source,n),ast.unparse(replacement)))
            elif isinstance(n,ast.ImportFrom):
                base=absolute_from(relative,n);replacement=deepcopy(n)
                if base==old or base.startswith(old+'.'):
                    replacement.module=new+base[len(old):];replacement.level=0
                elif base==old.rpartition('.')[0]:
                    for a in replacement.names:
                        if a.name==old.rpartition('.')[2]:a.asname=a.asname or a.name;a.name=new.rpartition('.')[2]
                if ast.dump(replacement)!=ast.dump(n):changes.append((*span(source,n),ast.unparse(replacement)))
            elif isinstance(n,ast.Attribute) and not isinstance(parents.get(n),ast.Attribute):
                spelling=ast.unparse(n)
                if spelling.startswith(old+'.'):changes.append((*span(source,n),new+spelling[len(old):]))
        updated=edits(source,changes) if changes else source
        if relative==oldpath or package and relative.startswith(oldpath+'/'):
            moved=newpath+relative[len(oldpath):]
            if moved in files:raise ValueError('module move collision')
            result[moved]=updated
            if not copy_only:result.pop(relative,None)
        elif not copy_only:result[relative]=updated
    return result,new


def render(files,site,family,control):
    base=dict(files);branches={};augmentation=False;new=site['name']+'_mutated'
    extra,extra_module=backup(site)
    if extra in files:raise ValueError('backup module collision')
    if family in {'conjunctive','fix_by_third'}:
        base[extra]=files[site['path']];augmentation=True
    guard=GAP+f"try:\n    from {extra_module} import {site['name']} as {site['name']}\nexcept ImportError:\n    pass\n"
    if family=='conjunctive':
        base[site['path']]+=guard
        a=dict(base);n=declaration(a[site['path']],site)
        a[site['path']]=edits(a[site['path']],[(*span(a[site['path']],n),'')])
        b=dict(base);b[site['path']]=b[site['path']].replace(guard,GAP)
        if control=='compatible':a=dict(base)
        elif control=='unrelated':b=dict(base)
        elif control=='coordinated':a=dict(base);b=dict(base)
        branches={'A':a,'B':b,'C':{**base,'mutation_consumer.py':consumer(files,site)}}
    elif family=='move_module':
        a,moved=move(base,site,copy_only=control=='compatible')
        b={**base,'mutation_consumer.py':consumer(files,site,unrelated=control=='unrelated')}
        if control=='coordinated':b={**a,'mutation_consumer.py':consumer(files,site,name=moved)}
        branches={'A':a,'B':b}
    else:
        a=arity(base,site,optional=control=='compatible') if family=='arity' else renamed(base,site,new)
        if family=='delete':
            a[extra]=a[site['path']]
            changed_site={**site,'name':new};node=declaration(a[site['path']],changed_site)
            a[site['path']]=edits(a[site['path']],[(*span(a[site['path']],node),f'from {extra_module} import {new} as {new}')])
        if family.startswith('open_'):
            a[extra]=files[site['path']]
            if family=='open_wildcard':a[site['path']]+=GAP+f'from {extra_module} import *\n'
            else:a[site['path']]+=GAP+f'from typing import Any\ndef __getattr__(name: str) -> Any:\n    if name == {site["name"]!r}:\n        return {new}\n    raise AttributeError(name)\n'
        if control=='compatible' and family=='fix_by_third':a=dict(base)
        elif control=='compatible' and family!='arity':a[site['path']]+=GAP+f'{site["name"]} = {new}\n'
        b={**base,'mutation_consumer.py':consumer(files,site,unrelated=control=='unrelated')}
        if control=='coordinated':
            use=consumer(files,site,name=new if family!='arity' else None)
            if family=='arity':
                where=use.rfind(')');opening=use.rfind('(',0,where)
                use=use[:where]+(', ' if where>opening+1 else '')+'_mutation_required=None'+use[where:]
            b={**a,'mutation_consumer.py':use}
        branches={'A':a,'B':b}
        if family=='fix_by_third':branches['C']={**base,site['path']:base[site['path']]+guard}
        if family=='five_mix':
            for label in ('C','D','E'):branches[label]={**base,f'mutation_{label}.md':f'Independent documentation edit {label}\n'}
    for state in [base,*branches.values()]:
        for path,source in state.items():
            if path.endswith('.py'):ast.parse(source)
    return {'base':base,'branches':{name:{p:state.get(p) for p in sorted(base.keys()|state.keys()) if state.get(p)!=base.get(p)} for name,state in branches.items()},
            'family':family,'control':control,'site':site,'augmentation':augmentation}
