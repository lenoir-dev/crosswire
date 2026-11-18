"""Go syntax for S16 neutral edits; no detector/oracle-derived expectations."""
from copy import deepcopy
import re

MODULE = 'example.invalid/crosswire/conformance'
GAP = ''.join(f'// stable integration separator {n:02d}\n' for n in range(16))
SUPPORTED = {'GO-1', 'GO-2', 'GO-3', 'GO-4'}


class NoCounterpart(ValueError):
    """An explicitly unsupported language capability is not a passing case."""


def identifier(name, exported=False):
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', name):
        raise ValueError('Unsupported logical Go identifier')
    return name[:1].upper()+name[1:] if exported and name!='_' else name


def apply(base, edits):
    state = deepcopy(base)
    for edit in edits:
        op = edit['op']
        if op == 'add_use':
            if edit['site'] in state['uses']: raise ValueError('Duplicate use identity')
            state['uses'][edit['site']] = {k:v for k,v in edit.items() if k!='op'}
        elif op == 'move_module':
            if edit['to'] in state['modules']: raise ValueError('Move destination exists')
            state['modules'][edit['to']] = state['modules'].pop(edit['module'])
        else:
            module = state['modules'][edit['module']]
            if op == 'add_declaration':
                module['declarations'].append({k:v for k,v in edit.items() if k not in {'op','module'}})
            elif op == 'delete':
                module['declarations'] = [d for d in module['declarations'] if d['id']!=edit['symbol']]
            elif op in {'rename','add_parameter'}:
                declaration = next(d for d in module['declarations'] if d['id']==edit['symbol'])
                if op=='rename': declaration['name'] = edit['to']
                else: declaration['parameters'].append({'name':edit['name'],'required':edit['required']})
            elif op=='add_forward':
                # Go cannot shadow a declaration with an import as Python can.
                # The alias replaces the direct binding on this branch; the
                # common direct deletion merges cleanly with the removal side.
                module['declarations'] = [d for d in module['declarations'] if d['id']!=edit['symbol']]
                module['forward'] = {'module':edit['from_module'],'symbol':edit['symbol']}
            else: raise ValueError('Unsupported Go operation: '+op)
    return state


def declaration(d):
    name=identifier(d.get('name', d['id']), exported=True)
    kind=d.get('kind','function'); value=d.get('value',1)
    if type(value) is not int: raise ValueError('Integer fixture value required')
    if kind=='type': return f'type {name} struct{{}}\n'
    if kind=='variable': return f'var {name} = {value}\n'
    if kind=='constant': return f'const {name} = {value}\n'
    if kind=='initializer':
        if d.get('name')!='init': raise ValueError('Initializer must name init')
        return 'func init() {}\n'
    if kind=='method': return f'func (T) {name}() int {{ return {value} }}\n'
    if kind!='function': raise ValueError('Unsupported declaration kind: '+kind)
    parameters=d.get('parameters',[]); chunks=[]
    for n,p in enumerate(parameters):
        optional=not p['required']
        if optional and n!=len(parameters)-1: raise ValueError('Only a trailing variadic is optional in Go')
        chunks.append(identifier(p['name'])+(' ...int' if optional else ' int'))
    body='value' if parameters and parameters[0]['name']=='value' else str(value)
    return f'func {name}({", ".join(chunks)}) int {{ return {body} }}\n'


def source_files(state):
    files={'go.mod':f'module {MODULE}\n\ngo 1.27.1\n'.encode()}; sites={}
    for name,module in sorted(state['modules'].items()):
        identifier(name); package=identifier(module['package'])
        groups={slot:[] for slot in module.get('slots',['direct','forward'])}
        for d in module['declarations']: groups.setdefault(d.get('file','api'),[]).append(d)
        # Regular templates use a single file with independent direct/alias
        # slots. Declaration-pair templates specify file and stable region.
        physical={}
        for slot,decls in sorted(groups.items()):
            path=(name+'/api.go') if slot in {'direct','forward'} else name+'/'+identifier(slot)+'.go'
            physical.setdefault(path,[]).append((slot,decls))
        if not physical: physical[name+'/api.go']=[]
        for path,slots in sorted(physical.items()):
            imports=[]; body=''
            for slot,decls in slots:
                body+='// slot '+slot+'\n'
                slot_imports=[]
                for d in sorted(decls,key=lambda d:d['id']):
                    if d.get('kind')=='import':
                        alias=identifier(d['name']); imported=identifier(d['from_module'])
                        slot_imports.append(f'// declaration {d["id"]} {alias} import\nimport {alias} "{MODULE}/{imported}"\n')
                        body+=f'var _ = {alias}.F\n'
                    else: body+=f'// declaration {d["id"]} {identifier(d.get("name",d["id"]),d.get("kind")!="initializer")} {d.get("kind","function")}\n'+declaration(d)
                if slot=='forward' and module.get('forward'):
                    f=module['forward']; imported=identifier(f['module'])
                    slot_imports.append(f'import forwarded "{MODULE}/{imported}"\n')
                    body+=f'var {identifier(f["symbol"],True)} = forwarded.{identifier(f["symbol"],True)}\n'
                body+=GAP
                imports.append('// import slot '+slot+'\n'+''.join(slot_imports)+GAP)
            files[path]=(f'package {package}\n\n'+''.join(imports)+'\n'+body).encode()
    for site,use in sorted(state['uses'].items()):
        path=identifier(use['file'])+'/consumer.go'; imported=identifier(use['module'])
        symbol=identifier(use['symbol'],True)
        if any(type(v) is not int for v in use['arguments']): raise ValueError('Integer fixture arguments required')
        args=', '.join(str(v) for v in use['arguments'])
        files[path]=(f'package consumer\n\nimport dependency "{MODULE}/{imported}"\n\n'
                     f'var _ = dependency.{symbol}({args})\n').encode()
        sites[site]={'path':path,'symbol':imported+'.'+symbol,'module':MODULE+'/'+imported,
                     'start_line':3,'end_line':5}
    return files,sites


def render(template,case):
    contract=template['contracts']['go']
    if contract['id'] not in SUPPORTED: raise NoCounterpart(template['id']+': no Go counterpart')
    base=deepcopy(template['base'])
    for name,module in base['modules'].items():
        module.setdefault('package',name)
        # Direct declarations share api.go with the separate alias slot.
        for d in module['declarations']: d.setdefault('file','direct')
    files,_=source_files(base); branches=[]; sites={}
    for branch in case['branches']:
        if branch['parent']!='target': raise ValueError('Go renderer requires independent target-based branches')
        changed,branch_sites=source_files(apply(base,branch['edits']))
        branches.append({'id':branch['id'],'parent':'target','files':{
            p:changed.get(p) for p in sorted(files.keys()|changed.keys()) if files.get(p)!=changed.get(p)}})
        sites.update(branch_sites)
    return {'language':'go','contract':{'id':contract['id'],'scope':'supported'},
            'base':files,'branches':branches,'sites':sites}
