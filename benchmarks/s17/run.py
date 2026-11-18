"""Preregister and replay a bounded natural M3 development stratum.

All writable state is under --root or --output. The sealed eval directory and
private holdout are neither imported nor opened. Only --preregister clones;
--measure requires a recorded apparatus freeze and selection before any oracle.
"""
import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import tarfile
import time

from conformance.git import environment, git, snapshot
from conformance.oracle import checker_provenance
from conformance.run import installed_provenance
from .identity import module_of
from .m3 import Identity, Observation, label, minimal_attribution
from .matching import RULES, match
from .metrics import aggregate, clustered
from .oracle import CONFIG, observe


ROOT=Path(__file__).resolve().parents[2]
POLICY=Path(__file__).with_name('policy.json')
FREEZE=ROOT/'docs/validation/s17-m3-freeze.json'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def oracle_environment_sha256(python):
    directory=Path(subprocess.check_output([python,'-I','-c','import sysconfig; print(sysconfig.get_path("purelib"))']).decode().strip())
    digest=hashlib.sha256()
    for path in sorted(directory.rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts and path.suffix!='.pyc':
            digest.update(path.relative_to(directory).as_posix().encode()+b'\0'+path.read_bytes()+b'\0')
    return digest.hexdigest()


def portable(value,root):
    if isinstance(value,dict):return {k:portable(v,root) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [portable(v,root) for v in value]
    if isinstance(value,str):return value.replace(str(root),'${S17_ROOT}').replace(str(Path.home()),'${HOME}')
    return value


def write(path,value,root):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(portable(value,root),sort_keys=True,indent=2)+'\n');temporary.replace(path)


def verify_freeze():
    frozen=json.loads(FREEZE.read_text())
    for path,digest in frozen['files_sha256'].items():
        if sha(ROOT/path)!=digest:raise ValueError('M3 freeze drift: '+path)
    return frozen


def files_at(repo,revision):
    content=git(repo,'archive',revision).stdout
    files={};stubs=[];invalid=[]
    with tarfile.open(fileobj=io.BytesIO(content)) as stream:
        for entry in stream.getmembers():
            path=entry.name
            if any(p.startswith('.') for p in Path(path).parts):continue
            if path.endswith('.pyi'):stubs.append(path)
            if not path.endswith('.py'):continue
            if not entry.isfile():invalid.append(path);continue
            try:files[path]=stream.extractfile(entry).read().decode('utf-8')
            except UnicodeError:invalid.append(path)
    return files,stubs,invalid


def scope(paths,roots):
    names={'test','tests','testing','testsuite','_tests'}
    return sorted(p for p in paths if any(p==r or p.startswith(r.rstrip('/')+'/') for r in roots)
                  or any(part in names for part in Path(p).parts[:-1])
                  or len(Path(p).parts)==1 and Path(p).name.startswith('test'))


def rename_map(repo,target,state):
    data=git(repo,'diff','--name-status','--find-renames=100%','-z',target,state).stdout.split(b'\0')
    result={};i=0
    while i<len(data) and data[i]:
        status=data[i].decode();i+=1
        if status.startswith(('R','C')):
            old,new=data[i].decode(),data[i+1].decode();i+=2
            if status.startswith('R'):result[old]=new
        else:i+=1
    return result


def preregister(root,output,policy):
    path=output/'selection.json'
    if path.exists():raise ValueError('Selection already preregistered; do not replace it')
    selections=[]
    for spec in policy['repositories']:
        repo=root/'repositories'/spec['id'];repo.parent.mkdir(parents=True,exist_ok=True)
        if not repo.exists():subprocess.run(['git','clone','--quiet',spec['url'],str(repo)],check=True,timeout=180)
        head=git(repo,'rev-parse','HEAD').stdout.decode().strip()
        selected=[];examined=0
        for line in git(repo,'rev-list','--timestamp','--min-parents=2','--max-parents=2','--parents',head).stdout.decode().splitlines():
            stamp,commit,*parents=line.split();examined+=1
            bases=git(repo,'merge-base','--all',*parents).stdout.decode().splitlines()
            if len(bases)!=1 or bases[0] in parents:continue
            changed=git(repo,'diff','--name-only',bases[0],commit).stdout.decode().splitlines()
            if not any(p.endswith('.py') for p in changed):continue
            selected.append({'merge':commit,'parents':parents,'target':bases[0],'timestamp':int(stamp)})
        selected.sort(key=lambda c:(-c['timestamp'],c['merge']))
        selected=selected[:policy['limit_per_repository']]
        selections.append({**spec,'head':head,'examined_two_parent_merges':examined,'cases':selected})
    result={'apparatus_freeze_sha256':sha(FREEZE),'policy_sha256':sha(POLICY),'selection_rule':policy['selection'],
            'repositories':selections,'selected_cases':sum(len(s['cases']) for s in selections)}
    write(path,result,root)
    print(json.dumps({'status':'preregistered; no oracle run','repositories':len(selections),'cases':result['selected_cases']}),flush=True)


def observation_from(value):
    def identities(items):return tuple(None if x is None else Identity(**x) for x in items)
    return Observation(identities(value['diagnostics']),complete=value['complete'],environment_failure=value['environment_failure'],
        ambiguous=value['ambiguous'],supported=None if value['supported'] is None else identities(value['supported']))


def metric_rows(cases,rule=None):
    return [{'repository':c['repository'],'eligible':c['eligible'],**(c['metrics'] if rule is None else c['by_rule'][rule]),
             'detector_error':bool(c.get('detector_error'))} for c in cases]


def measure(root,output,policy,checker_python,detector_python):
    freeze=verify_freeze();selection=json.loads((output/'selection.json').read_text())
    if selection['apparatus_freeze_sha256']!=sha(FREEZE) or selection['policy_sha256']!=sha(POLICY):raise ValueError('Selection/freeze mismatch')
    checker=checker_provenance(checker_python);checker['config']=CONFIG
    detector=installed_provenance(detector_python)
    expected=freeze['detector_package_files_sha256']
    if detector['package_files_sha256']!=expected:raise ValueError('Installed detector is not frozen HEAD '+policy['detector_commit'])
    if checker!=freeze['checker']:raise ValueError('Oracle toolchain differs from M3 freeze')
    if oracle_environment_sha256(checker_python)!=freeze['oracle_environment_sha256']:raise ValueError('Oracle dependency tree differs from M3 freeze')
    header={'stratum':policy['stratum'],'freeze_sha256':sha(FREEZE),'selection_sha256':sha(output/'selection.json'),
            'detector_commit':policy['detector_commit'],'detector':detector,'checker':checker}
    cases=[];start=time.monotonic()
    for spec in selection['repositories']:
        repo=root/'repositories'/spec['id']
        if git(repo,'rev-parse','HEAD').stdout.decode().strip()!=spec['head']:raise ValueError('Pinned repository HEAD drift')
        for item in spec['cases']:
            case_path=output/'cases'/spec['id']/(item['merge']+'.json')
            if case_path.exists():
                old=json.loads(case_path.read_text())
                if old['freeze_sha256']!=header['freeze_sha256'] or old['selection_sha256']!=header['selection_sha256']:raise ValueError('Case provenance mismatch')
                cases.append(old);continue
            case={'repository':spec['id'],'url':spec['url'],**item,'freeze_sha256':header['freeze_sha256'],
                  'selection_sha256':header['selection_sha256'],'eligible':False,'label':'unlabelled',
                  'metrics':{'tp':0,'fp':0,'fn':0,'unlabelled_predictions':0},
                  'by_rule':{r:{'tp':0,'fp':0,'fn':0,'unlabelled_predictions':0} for r in RULES}}
            merge=git(repo,'merge-tree','--write-tree',*item['parents'],check=False)
            if merge.returncode==1:case['exclusion']='textual-conflict'
            elif merge.returncode!=0:case['exclusion']='merge-tree-failure'
            else:
                tree=merge.stdout.splitlines()[0].decode()
                integrated=git(repo,'-c','commit.gpgSign=false','commit-tree',tree,'-p',item['parents'][0],'-p',item['parents'][1],input=b'S17 native integration\n').stdout.decode().strip()
                case.update(native_tree=tree,native_commit=integrated,recorded_tree=git(repo,'rev-parse',item['merge']+'^{tree}').stdout.decode().strip())
                revisions={'target':item['target'],'A':item['parents'][0],'B':item['parents'][1],'integrated':integrated}
                sources={};stubs=[];invalid=[]
                for name,revision in revisions.items():
                    data,stub,bad=files_at(repo,revision);sources[name]=data;stubs+=stub;invalid+=bad
                includes=scope(set().union(*(data.keys() for data in sources.values())),spec['roots'])
                known={};duplicates=[]
                for path in includes:
                    module=module_of(path)
                    if module in known and known[module]!=path:duplicates.append(module)
                    known[module]=path
                maps={name:rename_map(repo,item['target'],revision) for name,revision in revisions.items() if name!='target'}
                case.update(scope=includes,path_maps=maps,known_modules=known)
                if any(p in includes for p in invalid):case['exclusion']='non-utf8-or-nonregular-python-source'
                elif any(path in scope(stubs,spec['roots']) for path in stubs):case['exclusion']='stub-dependent-context'
                elif not includes:case['exclusion']='empty-oracle-scope'
                elif duplicates:case['exclusion']='ambiguous-module-roots'
                else:
                    observations={};evidence={}
                    scoped={name:{p:s for p,s in data.items() if p in includes} for name,data in sources.items()}
                    with tempfile.TemporaryDirectory(prefix='oracle-',dir=root) as temporary:
                        for name,files in scoped.items():
                            observations[name],evidence[name]=observe(files,Path(temporary)/name,checker_python,known_modules=known,include=includes)
                    result=label(observations['target'],{n:observations[n] for n in ('A','B')},observations['integrated'],maps)
                    case.update(eligible=result['eligible'],label=result['label'],exclusion=result['reason'],oracle=evidence)
                    diagnostics=result['diagnostics'];case['new_supported_diagnostics']=[asdict(d) for d in diagnostics]
                    if case['eligible']:
                        args=['check','--repo',str(repo),'--target',item['target'],'--combined','--no-cache','--src','src','--src','lib','--src','.',
                              '--format','json',*item['parents']]
                        before=snapshot(repo)
                        try:
                            executed=subprocess.run([detector_python,'-I','-B','-m','crosswire',*args],env=environment(),cwd=root,capture_output=True,timeout=90)
                            raw=json.loads(executed.stdout)
                            if executed.returncode not in (0,1) or not isinstance(raw.get('findings'),list):raise ValueError('invalid detector output')
                            findings=raw['findings'];case['detector']={'exit':executed.returncode,'report':raw,'stderr':executed.stderr.decode('utf-8','replace')}
                        except (OSError,ValueError,subprocess.TimeoutExpired) as error:
                            findings=[];case['detector_error']=type(error).__name__
                        if before!=snapshot(repo):raise ValueError('Detector changed repository HEAD/index/refs/config/worktree')
                        matched=match(findings,diagnostics,scoped['target'],scoped['integrated'],known)
                        case['metrics'].update(tp=matched['tp'],fp=matched['fp'],fn=matched['fn'],unlabelled_predictions=len(matched['unlabelled']))
                        case['false_positives']=matched['false_positives'];case['misses']=[{'type':m['type'],'diagnostics':[asdict(d) for d in m['diagnostics']],'reason':m['reason']} for m in matched['misses']]
                        case['unlabelled_predictions']=matched['unlabelled'];case['attribution']=[]
                        for hit in matched['matches']:
                            finding=hit['finding'];ids={item['parents'][0]:'A',item['parents'][1]:'B',item['target']:'target'}
                            owner=ids.get(finding.get('branch'));culprits=[ids.get(x) for x in finding.get('culprits',[])]
                            selected={x for x in [owner,*culprits] if x not in {None,'target'}}
                            states={frozenset():observations['target'],frozenset({'A'}):observations['A'],frozenset({'B'}):observations['B'],frozenset({'A','B'}):observations['integrated']}
                            attribution=minimal_attribution(observations['target'],states,selected,hit['diagnostic']) if selected and None not in culprits else None
                            case['attribution'].append({'rule':finding['rule'],'confirmed':attribution})
                        for rule in RULES:
                            hits=[m for m in matched['matches'] if m['finding']['rule']==rule]
                            case['by_rule'][rule].update(tp=len(hits),fp=sum(x['finding']['rule']==rule for x in matched['false_positives']),
                                fn=sum(('CW002' if x['type']=='PY-4' else 'CW006' if x['type']=='PY-5' else 'CW001')==rule for x in matched['misses']),
                                unlabelled_predictions=sum(x['finding']['rule']==rule for x in matched['unlabelled']))
                        case['warning_counts']={r:sum(f.get('rule')==r for f in findings) for r in ('CW003','CW004','CW005')}
            write(case_path,case,root);cases.append(portable(case,root))
            print(json.dumps({'repository':case['repository'],'merge':case['merge'][:12],'label':case['label'],'exclusion':case.get('exclusion')}),flush=True)
            verify_freeze()
    result={**header,'detector_execution_scope':'oracle-eligible cases only; emitted prediction rate over excluded cases is not estimable',
        'cases':cases,'summary':aggregate(metric_rows(cases)),'repo_clustered95':clustered(metric_rows(cases)),
        'by_rule':{r:{**aggregate(metric_rows(cases,r)),'repo_clustered95':clustered(metric_rows(cases,r))} for r in RULES},
        'repositories':{s['id']:{'attempted':sum(c['repository']==s['id'] for c in cases),'eligible':sum(c['repository']==s['id'] and c['eligible'] for c in cases)} for s in selection['repositories']},
        'labels':dict(Counter(c['label'] for c in cases)),'exclusions':dict(Counter(c.get('exclusion') for c in cases if not c['eligible'])),
        'seconds':time.monotonic()-start,'source_stable':installed_provenance(detector_python)==detector,
        'oracle_stable':checker_provenance(checker_python)|{'config':CONFIG}==checker and oracle_environment_sha256(checker_python)==freeze['oracle_environment_sha256'],
        'apparatus_stable':True}
    verify_freeze();write(output/'results.json',result,root)
    print(json.dumps({k:result[k] for k in ('summary','repositories','labels','exclusions','source_stable')}),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--preregister',action='store_true');parser.add_argument('--measure',action='store_true')
    parser.add_argument('--checker-python');parser.add_argument('--detector-python')
    args=parser.parse_args();root=args.root.resolve();output=args.output.resolve();root.mkdir(parents=True,exist_ok=True)
    verify_freeze();policy=json.loads(POLICY.read_text())
    if args.preregister:preregister(root,output,policy)
    elif args.measure:
        if not args.checker_python or not args.detector_python:parser.error('Explicit installed detector and pinned checker interpreters required')
        measure(root,output,policy,str(Path(args.checker_python).absolute()),str(Path(args.detector_python).absolute()))
    else:parser.error('Choose --preregister or --measure')


if __name__=='__main__':main()
