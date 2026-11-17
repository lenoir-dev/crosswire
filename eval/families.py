"""R2 development scaffold families on pinned real-repository source snapshots.

These supplemental scenarios explicitly use an oracle probe wrapping an upstream
API object; they are not mined incidents or mutations of an upstream declaration.
Reserved holdout parameters/generation are retained privately.
"""
import ast
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess

from .corpus import candidates, create_repo, git
from .oracle import occurrence, run, scope

FAMILIES=('remove_attribute','from_import','module_move','remove_reexport','class_remove',
          'required_keyword','unknown_keyword','too_many_positional','required_posonly','init_required',
          'conjunctive')
HARD_NEGATIVES=('optional_parameter','star_export','dynamic_export','package_ification','submodule_reexport','same_name_other_module')
GAP=''.join(f'# stable integration separator {i}\n' for i in range(15))


def anchor(screen, index=0):
    functions=candidates(Path(screen['path']),screen['roots'])
    if functions:
        candidate=functions[index % len(functions)]
        return candidate['module'], candidate['name']
    from .corpus import module_for
    for root in screen['roots']:
        paths=[Path(screen['path'])/root] if root.endswith('.py') else sorted((Path(screen['path'])/root).rglob('*.py'))
        for path in paths:
            tree=ast.parse(path.read_text())
            for node in tree.body:
                if isinstance(node,ast.ClassDef) and not node.name.startswith('_'):
                    return module_for(path.relative_to(screen['path']).as_posix(),screen['roots']),node.name
                if isinstance(node,(ast.Assign,ast.AnnAssign)):
                    targets=node.targets if isinstance(node,ast.Assign) else [node.target]
                    names=[n.id for t in targets for n in ast.walk(t) if isinstance(n,ast.Name) and not n.id.startswith('_')]
                    if names:
                        return module_for(path.relative_to(screen['path']).as_posix(),screen['roots']),names[0]
    raise ValueError('No usable upstream anchor')


def build(screen, directory, family, kind, variant, python, checker, package=None):
    """Label target, every tip, final state and all claimed minimality trials."""
    create_repo(screen,directory)
    package=package or f'crosswire_probe_{variant:03d}'
    pkg=directory/package;pkg.mkdir()
    module,name=anchor(screen,variant)
    prefix=f'from {module} import {name} as upstream_api\n'
    direct='def f(value: int) -> object:\n    return upstream_api\n'
    support=prefix+direct
    fallback=f'try:\n    from {package}.support import f\nexcept ImportError:\n    pass\n'
    original=prefix+direct
    consumer='crosswire_eval_use.py'
    use=f'import {package}.api as api\napi.f(1)\n'
    symbol=f'{package}.api.f'
    type_='PY-1'
    files={'__init__.py':'','support.py':support,'api.py':original}
    changed=prefix+'# binding removed\n'
    second=None
    if family=='from_import':
        use=f'from {package}.api import f\nf(1)\n'
    elif family=='module_move':
        type_='PY-2'
    elif family=='remove_reexport':
        original=f'from {package}.support import f as f\n';changed='# reexport removed\n';type_='PY-3'
    elif family=='class_remove':
        original=prefix+'class Factory:\n    pass\n';changed=prefix+'# class removed\n';use=f'import {package}.api as api\napi.Factory()\n';symbol=f'{package}.api.Factory'
    elif family=='required_keyword':
        changed=prefix+'def f(value: int, *, template: str) -> object:\n    return upstream_api\n';type_='PY-4'
    elif family=='unknown_keyword':
        changed=prefix+'def f(renamed: int) -> object:\n    return upstream_api\n';use=f'import {package}.api as api\napi.f(value=1)\n';type_='PY-4'
    elif family=='too_many_positional':
        changed=prefix+'def f() -> object:\n    return upstream_api\n';type_='PY-4'
    elif family=='required_posonly':
        changed=prefix+'def f(value: int, /) -> object:\n    return upstream_api\n';use=f'import {package}.api as api\napi.f(value=1)\n';type_='PY-4'
    elif family=='init_required':
        original=prefix+'class Factory:\n    def __init__(self) -> None:\n        self.api = upstream_api\n';changed=original.replace('self) ->','self, *, template: str) ->');use=f'import {package}.api as api\napi.Factory()\n';symbol=f'{package}.api.Factory';type_='PY-4'
    elif family=='conjunctive':
        original=prefix+direct+GAP+fallback
        changed=prefix+'# direct binding removed\n'+GAP+fallback
        second=prefix+direct+GAP+'# fallback removed\n'
        type_='PY-5'
    files['api.py']=original
    if kind=='compatible' and HARD_NEGATIVES[variant % len(HARD_NEGATIVES)]=='submodule_reexport':
        files['__init__.py']='from . import api as api\n'
    if kind=='compatible' and HARD_NEGATIVES[variant % len(HARD_NEGATIVES)]=='same_name_other_module':
        files['other.py']='def f(value: int) -> int:\n    return value\n'
    for path,content in files.items():(pkg/path).write_text(content)
    git(directory,'add',package);git(directory,'commit','-m','oracle probe of pinned upstream API')
    target=git(directory,'rev-parse','HEAD')
    roots=[*screen['roots'],package,consumer]
    oracles={}
    def check(label,sha):
        git(directory,'checkout','--detach',sha)
        result=run(directory,roots,python,checker)
        oracles[label]=asdict(result)
        return result
    baseline=check('target',target)
    hard=None
    if kind!='positive':
        # Hard negatives share the positive use site but preserve its callable.
        hard=HARD_NEGATIVES[variant % len(HARD_NEGATIVES)] if kind=='compatible' else 'unrelated' if kind=='unrelated' else 'coordinated'
        if hard=='star_export':changed=f'from {package}.support import *\n'
        elif hard=='dynamic_export':changed=f'from {package}.support import f as _shim\nfrom typing import Any\ndef __getattr__(name: str) -> Any:\n    return _shim\n'
        elif hard=='optional_parameter' and family not in {'class_remove','init_required'}:changed=original+'\noptional_extension = True\n' if family=='conjunctive' else prefix+'def f(value: int = 1, *, optional: str = "") -> object:\n    return upstream_api\n'
        else:changed=original+'\n# compatible independent extension\n'
        if family in {'class_remove','init_required'} and hard in {'star_export','dynamic_export'}:
            # Preserve the class binding for class-specific controls too.
            changed=original+'\n# compatible class extension\n'
        if family=='conjunctive':second=original+'\n# fallback preserved\n'
        if kind=='coordinated':
            old='Factory' if family in {'class_remove','init_required'} else 'f'
            new=old+'_compatible'
            import re
            changed=prefix+re.sub(r'\b'+old+r'\b',new,original.removeprefix(prefix)) if original.startswith(prefix) else original.replace('import f as f','import f as '+new)
            if family=='conjunctive':
                changed=changed.replace('import '+new, 'import f as '+new)
                second=changed
            use=re.sub(r'\b'+old+r'\b',new,use)
            symbol=symbol.rsplit('.',1)[0]+'.'+new
    tips={}
    def tip(label,changes):
        git(directory,'checkout','-b',label,target)
        for path,content in changes.items():
            p=directory/path
            if content is None:p.unlink()
            else:p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content)
        git(directory,'add',package,consumer) if (directory/consumer).exists() else git(directory,'add',package)
        git(directory,'commit','--allow-empty','-m',label+' '+family+' '+kind)
        tips[label]=git(directory,'rev-parse','HEAD');check(label,tips[label])
    changes={f'{package}/api.py':changed}
    if family=='module_move' and kind=='positive':changes={f'{package}/api.py':None,f'{package}/moved.py':original}
    elif hard=='package_ification':changes={f'{package}/api.py':None,f'{package}/api/__init__.py':original}
    elif hard=='submodule_reexport':
        # The use is of a package submodule which remains present after dropping __init__'s import.
        changes={f'{package}/__init__.py':''};use=f'from {package} import api\napi.'+('Factory()\n' if family in {'class_remove','init_required'} else 'f(1)\n')
    elif hard=='same_name_other_module':changes={f'{package}/other.py':'# removed f from an unrelated module; api.f remains intact\n'}
    tip('A',changes)
    owner='C' if family=='conjunctive' else 'B'
    if second is not None:
        if kind!='positive' and kind!='coordinated':tip('B',{f'{package}/independent_note.txt':'compatible third branch\n'})
        else:tip('B',{f'{package}/api.py':second})
    owner_changes={consumer:use}
    if kind=='coordinated':owner_changes[f'{package}/api.py']=changed
    tip(owner,owner_changes)
    def merge(labels):
        current=target
        for label in labels:
            r=subprocess.run(['git','merge-tree','--write-tree',current,tips[label]],cwd=directory,capture_output=True,text=True)
            if r.returncode:return None
            tree=r.stdout.splitlines()[0]
            current=git(directory,'-c','commit.gpgSign=false','commit-tree',tree,'-p',current,'-p',tips[label],'-m','native oracle integration')
        return current
    integrated=merge(list(tips))
    if integrated is None:return {'eligible':False,'exclusion':'textual-conflict','family':family,'kind':kind}
    final=check('integrated',integrated)
    eligible=baseline.status=='pass' and all(oracles[k]['status']=='pass' for k in tips) and final.status!='unlabelled'
    errors=[d for d in final.diagnostics if Path(d['file']).name==consumer and d.get('rule') in {'reportCallIssue','reportAttributeAccessIssue','reportMissingImports'}]
    eligible &= bool(errors) if kind=='positive' else final.status=='pass'
    culprits=[b for b in tips if b!=owner]
    trials=[]
    if kind=='positive':
        statuses=[]
        for removed in culprits:
            subset=[b for b in tips if b!=removed]
            sha=merge(subset)
            result=check('without-'+removed,sha) if sha else None
            statuses.append(result.status if result else 'unlabelled')
        confirmed=True if eligible and all(s=='pass' for s in statuses) else None
        trials=[{'branch':owner,'culprits':culprits,'confirmed':confirmed,'full':'integrated','single_removal':{c:'without-'+c for c in culprits}}]
    from itertools import combinations
    states={'':{'status':baseline.status}}
    for size in range(1,len(tips)+1):
        for labels in combinations(tips,size):
            key='+'.join(sorted(labels))
            label=labels[0] if len(labels)==1 else 'integrated' if len(labels)==len(tips) else next(('without-'+b for b in tips if b not in labels),None)
            if label not in oracles:
                sha=merge(labels)
                if sha:check('state:'+key,sha);label='state:'+key
            states[key]={'status':oracles[label]['status']} if label in oracles else {'status':'unlabelled'}
    git(directory,'checkout','--detach',integrated)
    (directory/'.crosswire-eval-pyright.json').unlink(missing_ok=True)
    patches={label:git(directory,'diff',target,sha) for label,sha in tips.items()}
    return {'repository':screen['repository'],'upstream_sha':screen['sha'],'materialization':screen.get('materialization','full upstream tree'),'roots':screen['roots'],'oracle_roots':scope(directory,roots),'path':str(directory),'target':target,'tips':tips,'integrated':integrated,'eligible':bool(eligible),'exclusion':None if eligible else 'oracle-ineligible','kind':kind,'family':family,'hard_negative':hard,'type':type_,'symbol':symbol,'consumer':consumer,'consumer_source':use,'oracle':oracles,'oracle_positive':bool(errors),'attribution_trials':trials,'oracle_states':states,'patches':patches,'stratum':'upstream API oracle scaffolds'}
