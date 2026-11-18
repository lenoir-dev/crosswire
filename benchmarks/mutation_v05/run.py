"""Preregister, freeze, then measure the development-only mutation corpus."""
import argparse
from collections import Counter
from dataclasses import asdict,is_dataclass
import hashlib
from itertools import combinations
import io
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile

from conformance import git
from conformance.oracle import checker_provenance
from conformance.run import installed_provenance
from benchmarks.s17.identity import module_of
from benchmarks.s17.m3 import label,minimal_attribution
from benchmarks.s17.oracle import observe,CONFIG
from benchmarks.s17.matching import match,RULES
from benchmarks.s17.metrics import aggregate,clustered
from benchmarks.s17.run import scope,oracle_environment_sha256,observation_from,rename_map
from .render import select_sites,render

ROOT=Path(__file__).resolve().parents[2]
DIRECTORY=Path(__file__).parent
POLICY=DIRECTORY/'policy.json'
SELECTION=ROOT/'docs/validation/mut-v05-selection.json'
FREEZE=ROOT/'docs/validation/mut-v05-freeze.json'
MODES=('pairwise','combined','plan')


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def normalized(value,root):
    if is_dataclass(value):return normalized(asdict(value),root)
    if isinstance(value,dict):return {k:normalized(v,root) for k,v in value.items()}
    if isinstance(value,(tuple,list)):return [normalized(v,root) for v in value]
    if isinstance(value,str):return value.replace(str(root),'${MUTATION_ROOT}').replace(str(Path.home()),'${HOME}')
    return value


def write(path,value,root):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(normalized(value,root),sort_keys=True,indent=2)+'\n')


def archive_files(repo,revision,only_python=False):
    raw=git.git(repo,'archive',revision).stdout;result={}
    with tarfile.open(fileobj=io.BytesIO(raw)) as stream:
        for entry in stream:
            if entry.isfile() and (not only_python or entry.name.endswith('.py')):
                result[entry.name]=stream.extractfile(entry).read()
    return result


def preregister(root):
    if SELECTION.exists():raise ValueError('Selection already exists; never replace it')
    policy=json.loads(POLICY.read_text());selected=[];cases=[]
    for spec in policy['repositories']:
        repo=root/'repositories'/spec['id']
        if not repo.exists():
            repo.parent.mkdir(parents=True,exist_ok=True)
            subprocess.run(['git','clone','--quiet',spec['url'],str(repo)],check=True,timeout=180)
        files={p:b.decode() for p,b in archive_files(repo,spec['sha'],True).items()}
        sites=select_sites(files,spec,policy['seed'])
        selected.append({**spec,'sites':sites,'upstream_tree':git.git(repo,'rev-parse',spec['sha']+'^{tree}').stdout.decode().strip(),
                         'python_files_sha256':{p:hashlib.sha256(s.encode()).hexdigest() for p,s in files.items()}})
        for site in sites:
            for family in policy['families'][site['kind']]:
                for control in ('scenario',*policy['controls']):
                    key='|'.join([spec['id'],site['kind'],site['path'],site['name'],family,control])
                    cases.append({'id':hashlib.sha256(key.encode()).hexdigest()[:20],'repository':spec['id'],
                                  'site':site,'family':family,'control':control})
    write(SELECTION,{'stratum':'mutation','policy_sha256':sha(POLICY),'repositories':selected,'cases':cases},root)
    print(json.dumps({'stage':'preregistered; no labels','sites':sum(len(s['sites']) for s in selected),'cases':len(cases)}),flush=True)


def freeze(root,checker_python,detector_python):
    if FREEZE.exists():raise ValueError('Freeze exists; do not alter after labels')
    selected=json.loads(SELECTION.read_text());policy=json.loads(POLICY.read_text())
    assert selected['policy_sha256']==sha(POLICY)
    checker=checker_provenance(checker_python);checker['config']=CONFIG
    detector=installed_provenance(detector_python)
    source_files=git.git(ROOT,'ls-tree','-r','--name-only',policy['detector_commit'],'src/crosswire').stdout.decode().splitlines()
    expected={p.removeprefix('src/crosswire/'):hashlib.sha256(git.git(ROOT,'show',policy['detector_commit']+':'+p).stdout).hexdigest() for p in source_files}
    assert expected==detector['package_files_sha256'],'Installed wheel differs from pinned Git source'
    probe=subprocess.check_output([checker_python,'-I','-c','import importlib.util,json; print(json.dumps({n:importlib.util.find_spec(n) is None for n in ["sniffio","iniconfig","pytest_repeat","certifi","trove_classifiers"]}))'],text=True)
    assert all(json.loads(probe).values()),'First-party site-packages shadowing risk'
    paths=[p for p in DIRECTORY.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    paths += [ROOT/'tests/test_mutation_v05.py',ROOT/'docs/validation/matching.md']
    paths += list((ROOT/'conformance').rglob('*.py'))
    paths += [ROOT/f'benchmarks/s17/{name}.py' for name in ('m3','identity','oracle','matching','metrics','run')]
    paths += [ROOT/'benchmarks/s17/__init__.py']
    paths += list((ROOT/'conformance/templates').glob('*.json'))
    value={'stratum':'mutation','stage':'FROZEN before first real-repository mutation label',
           'selection_sha256':sha(SELECTION),'files_sha256':{p.relative_to(ROOT).as_posix():sha(p) for p in sorted(paths)},
           'checker':checker,'oracle_environment_sha256':oracle_environment_sha256(checker_python),
           'detector_commit':policy['detector_commit'],'detector':detector,
           'controller':{'version':sys.version,'sha256':sha(Path(sys.executable).resolve()),'ast_sha256':sha(__import__('ast').__file__)},
           'git':subprocess.check_output(['git','--version'],text=True).strip(),'git_sha256':sha(Path(shutil.which('git')).resolve()),'platform':platform.platform(),
           'synthetic_tests':'Selector/renderer and pinned-checker M3 control/topology tests passed before freeze'}
    write(FREEZE,value,root)
    print(json.dumps({'stage':'frozen; no real-repository labels','freeze_sha256':sha(FREEZE)}),flush=True)


def verify():
    frozen=json.loads(FREEZE.read_text())
    assert frozen['selection_sha256']==sha(SELECTION)
    for p,h in frozen['files_sha256'].items():
        if sha(ROOT/p)!=h:raise ValueError('Mutation freeze drift: '+p)
    return frozen


def empty_mode(reason):return {'eligible':False,'label':'unlabelled','exclusion':reason,'tp':0,'fp':0,'fn':0,'unlabelled_predictions':0}


def oracle(files,include,known,root,python):
    key=digest({'files':files,'include':include,'known':known,'config':CONFIG})
    path=root/'oracle-cache'/(key+'.json')
    if path.exists():raw=json.loads(path.read_text());return observation_from(raw['observation']),key
    with tempfile.TemporaryDirectory(prefix='oracle-',dir=root) as d:
        observation,evidence=observe(files,Path(d)/'state',python,known_modules=known,include=include)
    write(path,{'observation':observation,'evidence':evidence,'sources':files},root)
    return observation,key


def score(repo,target,tips,states,observations,mappings,mode,known,detector_python,root):
    baseline=observations[frozenset()];labels=list(tips)
    full=frozenset(labels)
    trials=[frozenset(pair) for pair in combinations(labels,2)] if mode=='pairwise' else [full]
    diagnoses=set()
    for subset in trials:
        if subset not in observations:return empty_mode('textual-conflict-or-missing-state')
        maps={n:mappings[frozenset({n})] for n in subset};maps['integrated']=mappings[subset]
        result=label(baseline,{n:observations[frozenset({n})] for n in subset},observations[subset],maps)
        if not result['eligible']:return empty_mode(result['reason'])
        diagnoses.update(result['diagnostics'])
    base=states[frozenset()];integrated=states.get(full)
    if integrated is None:return empty_mode('textual-conflict-or-missing-full-state')
    command=['plan' if mode=='plan' else 'check','--repo',str(repo),'--target','main','--no-cache','--format','json','--src','src','--src','.']
    if mode=='combined':command.append('--combined')
    command += labels
    before=git.snapshot(repo);raw={};failure=None
    try:
        executed=subprocess.run([detector_python,'-I','-B','-m','crosswire',*command],cwd=root,env=git.environment(),capture_output=True,timeout=90)
        raw={'exit':executed.returncode,'stdout':executed.stdout.decode('utf-8','replace'),'stderr':executed.stderr.decode('utf-8','replace')}
        report=json.loads(executed.stdout)
        findings=[f for b in report['blocked'] for f in b['findings']] if mode=='plan' else report['findings']
        if executed.returncode not in (0,1):raise ValueError('detector exit')
        if not isinstance(findings,list) or any(not isinstance(f,dict) for f in findings):raise ValueError('detector findings')
    except (OSError,ValueError,KeyError,TypeError,subprocess.TimeoutExpired) as error:
        findings=[];failure=type(error).__name__
    assert git.snapshot(repo)==before,'Detector modified protected repository state'
    semantic=[f for f in findings if f.get('severity')=='error' and f.get('rule') in RULES]
    matched=match(semantic,tuple(sorted(diagnoses)),base,integrated,known)
    attribution=[]
    for hit in matched['matches']:
        finding=hit['finding'];owner=finding.get('branch');culprits=finding.get('culprits',[])
        selected=set(culprits)|({owner} if owner in tips else set())
        confirmed=minimal_attribution(baseline,observations,selected,hit['diagnostic'],mappings) if selected and selected<=set(tips) else None
        attribution.append({'rule':finding['rule'],'confirmed':confirmed})
    return {'eligible':True,'label':'positive' if diagnoses else 'control','exclusion':None,
        'tp':matched['tp'],'fp':matched['fp'],'fn':matched['fn'],'unlabelled_predictions':len(matched['unlabelled']),
        'detector_error':failure,'detector':raw,'diagnostics':tuple(sorted(diagnoses)),
        'matches':matched['matches'],'false_positives':matched['false_positives'],'misses':matched['misses'],
        'attribution':attribution,'unlabelled':matched['unlabelled'],
        'warnings':{r:sum(f.get('rule')==r for f in findings) for r in ('CW003','CW004','CW005')},
        'resolved_warnings':sum(bool(f.get('resolved_by')) for f in findings),
        'coverage':report.get('coverage') if not failure else None}


def measure(root,output,checker_python,detector_python):
    frozen=verify();selected=json.loads(SELECTION.read_text());specs={s['id']:s for s in selected['repositories']}
    assert installed_provenance(detector_python)==frozen['detector']
    provenance=checker_provenance(checker_python);provenance['config']=CONFIG
    assert provenance==frozen['checker'] and oracle_environment_sha256(checker_python)==frozen['oracle_environment_sha256']
    for item in selected['cases']:
        verify();destination=output/'cases'/(item['id']+'.json')
        if destination.exists():
            assert json.loads(destination.read_text())['freeze_sha256']==sha(FREEZE);continue
        case={**item,'stratum':'mutation','freeze_sha256':sha(FREEZE),'modes':{m:empty_mode('not-attempted') for m in MODES}}
        spec=specs[item['repository']];upstream=root/'repositories'/spec['id']
        content=archive_files(upstream,spec['sha'])
        files={p:b.decode() for p,b in content.items() if p.endswith('.py')}
        try:
            rendered=render(files,item['site'],item['family'],item['control']);case['augmentation']=rendered['augmentation']
            base={**content,**{p:s.encode() for p,s in rendered['base'].items()}}
            repo=root/'cases'/item['id'];repo.parent.mkdir(parents=True,exist_ok=True)
            if repo.exists():raise ValueError('Incomplete fixture exists; inspect before a new development run')
            target,tips=git.build(repo,{'base':base,'branches':[{'id':n,'files':{p:None if s is None else s.encode() for p,s in f.items()}} for n,f in rendered['branches'].items()]})
            if archive_files(repo,target,True)!={p:b for p,b in base.items() if p.endswith('.py')}:
                raise ValueError('Upstream ignore rules dropped baseline Python files')
            for name,patch in rendered['branches'].items():
                actual=archive_files(repo,tips[name],True)
                for p,s in patch.items():
                    if p.endswith('.py') and actual.get(p)!=(None if s is None else s.encode()):
                        raise ValueError('Mutation Python edit not recorded by Git')
            states={};commits={};labels=list(tips)
            for size in range(len(labels)+1):
                for subset in combinations(labels,size):
                    try:revision=git.integrate(repo,target,tips,list(subset))
                    except ValueError:continue
                    commits[frozenset(subset)]=revision
                    states[frozenset(subset)]={p:b.decode() for p,b in archive_files(repo,revision,True).items()}
            # Original production/test union plus every added mutation Python path.
            original=set(files);all_paths=set().union(*(set(v) for v in states.values()))
            include=sorted(set(scope(all_paths,spec['roots'])) | (all_paths-original))
            known={module_of(p):p for p in include}
            if len(known)!=len(include):raise ValueError('ambiguous module roots')
            observations={};refs={};mappings={subset:rename_map(repo,target,revision) for subset,revision in commits.items()}
            for subset,data in states.items():
                states[subset]={p:s for p,s in data.items() if p in include}
                observations[subset],key=oracle(states[subset],include,known,root,checker_python)
                refs['+'.join(sorted(subset)) or 'target']=key
            case.update(oracle_refs=refs,commits={'+'.join(sorted(k)) or 'target':v for k,v in commits.items()},
                        include=include,known_modules=known,rendered=rendered,
                        path_maps={'+'.join(sorted(k)) or 'target':v for k,v in mappings.items()})
            for mode in MODES:case['modes'][mode]=score(repo,target,tips,states,observations,mappings,mode,known,detector_python,root)
        except (ValueError,SyntaxError,UnicodeError,StopIteration) as error:
            case['structural_error']=type(error).__name__+': '+str(error)
            case['modes']={m:empty_mode('render-or-integration-context') for m in MODES}
        write(destination,case,root)
        print(json.dumps({'case':item['id'],'repository':item['repository'],'family':item['family'],'control':item['control'],
                          'labels':{m:v['label'] for m,v in case['modes'].items()}}),flush=True)
    verify()
    assert installed_provenance(detector_python)==frozen['detector']
    assert oracle_environment_sha256(checker_python)==frozen['oracle_environment_sha256']
    write(output/'complete.json',{'stratum':'mutation','freeze_sha256':sha(FREEZE),'cases':len(selected['cases']),
                                 'source_stable':True,'oracle_stable':True,'apparatus_stable':True},root)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',required=True,type=Path);p.add_argument('--output',type=Path)
    p.add_argument('--prepare',action='store_true');p.add_argument('--freeze',action='store_true');p.add_argument('--measure',action='store_true')
    p.add_argument('--checker-python');p.add_argument('--detector-python')
    args=p.parse_args();root=args.root.resolve();root.mkdir(parents=True,exist_ok=True)
    if args.prepare:preregister(root)
    elif args.freeze:freeze(root,args.checker_python,args.detector_python)
    elif args.measure:measure(root,args.output.resolve(),args.checker_python,args.detector_python)
    else:p.error('Choose prepare, freeze or measure')

if __name__=='__main__':main()
