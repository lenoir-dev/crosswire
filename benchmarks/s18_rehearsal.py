"""H1 rehearsal using ONLY generated private fixtures beneath a fresh temp root.

Never imports a private corpus locator. No real holdout path is accepted. Oracle
labels come from S16 contracts plus pinned checker/runtime checks, then synthetic
replicas exercise the frozen matching, seal, CLI, journals and aggregate export.
"""
import argparse
from copy import deepcopy
import hashlib
from itertools import combinations
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile

from conformance import git
from conformance.oracle import check, checker_provenance, validate
from conformance.render.python import render
from conformance.run import load_cases
from eval.integrity import apparatus, assert_case, digest, repository_hash
from eval.run_holdout import assert_aggregate_only, suppress_small_cells


ROOT=Path(__file__).resolve().parents[1]


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,sort_keys=True,indent=2)+'\n');path.chmod(0o600)


def archive(root):
    destination=root/'archive';destination.mkdir()
    for directory in ('eval','src'):
        shutil.copytree(ROOT/directory,destination/directory,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for relative in ('docs/validation/holdout.sha256','docs/validation/matching.md',
                     'docs/validation/v04-oracle-requirements.txt','docs/validation/v04-oracle-requirements.lock'):
        target=destination/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/relative,target)
    assert not (destination/'.git').exists()
    return destination


def seed_cases(root,python):
    seeds=[];oracle_states=0
    for _,template,case in load_cases():
        if template['id'] not in {'rename','arity','conjunctive'}:continue
        rendered=render(template,case);directory=root/'seeds'/case['id']
        target,tips=git.build(directory,rendered)
        labels=list(tips);observations={};commits={}
        for size in range(len(labels)+1):
            for subset in combinations(labels,size):
                name='+'.join(subset) or 'target'
                commit=git.integrate(directory,target,tips,list(subset));commits[name]=commit
                observations[name]=check(git.files_at(directory,commit),root/'oracle'/case['id']/name,python)
                oracle_states+=1
        validate(case,observations,rendered['sites'])
        full='+'.join(labels);integrated=commits[full]
        git.git(directory,'checkout','--quiet','--detach',integrated)
        site=rendered['sites'][case['oracle']['site']]
        sources=git.files_at(directory,integrated)
        row=dict(repository='synthetic',path=str(directory),eligible=True,target=target,tips=tips,
                 integrated=integrated,kind='positive' if case['kind']=='conflict' else 'compatible',
                 family=template['id'],type=rendered['contract']['id'],symbol=site['symbol'],
                 consumer=site['path'],consumer_source=sources[site['path']].decode(),roots=['.'],
                 oracle_positive=observations[full]['verdict']=='broken',
                 oracle={'integrated':{'diagnostics':observations[full]['diagnostics']}},
                 oracle_states={k:{'status':'fail' if v['verdict']=='broken' else 'pass'} for k,v in observations.items()})
        assert_case(row);seeds.append(row)
    assert len(seeds)==6
    return seeds,oracle_states


def private_fixture(root,archive,seeds,name):
    private=root/name;private.mkdir(mode=0o700);cases=[]
    for repository in range(4):
        for seed in seeds:
            for variant in range(5 if seed['kind']=='positive' else 15):
                case=deepcopy(seed);index=len(cases);directory=private/'cases'/f'{index:06d}'
                shutil.copytree(seed['path'],directory)
                case.update(path=str(directory),repository=f'synthetic-{repository}',id=f'synthetic-{index:06d}')
                # Copied Git indexes still contain seed inode/stat data. Let
                # Git refresh that cache BEFORE pinning this new fixture; never
                # mutate an index once the synthetic seal has been written.
                assert_case(case)
                case['repository_sha256']=repository_hash(directory);cases.append(case)
    assert len(cases)==240 and sum(c['kind']=='positive' for c in cases)==60
    write(private/'repositories.json',{str(n):c['repository_sha256'] for n,c in enumerate(cases)})
    write(private/'manifest.json',{'synthetic_private_fixture':True,'cases':cases,'apparatus':apparatus(archive)})
    pins={**apparatus(archive),'private/manifest.json':digest(private/'manifest.json'),
          'private/repositories.json':digest(private/'repositories.json')}
    seal=private/'synthetic.sha256'
    seal.write_text(''.join(f'{value}  {key}\n' for key,value in sorted(pins.items())));seal.chmod(0o600)
    return private,seal


def wrapper(private,*,kill_second=False):
    script=private/'detector-python';log=private/'invocations.log'
    # Paths are embedded ONLY into the generated private temporary script.
    script.write_text(f'''#!{sys.executable}
import os,signal,sys
from pathlib import Path
path=Path({str(log)!r})
if sys.argv[1:3]==['-m','crosswire']:
    with path.open('a') as stream:
        stream.write('invocation\\n');stream.flush();os.fsync(stream.fileno())
    if {kill_second!r} and len(path.read_text().splitlines())==2:
        os.kill(os.getppid(),signal.SIGKILL)
        sys.exit(77)
os.execv({sys.executable!r},[{sys.executable!r},*sys.argv[1:]])
''');script.chmod(0o700)
    return script,log


def invoke(archive,private,seal,freeze,detector,*,report_only=False):
    output=private/'public.json'
    command=[sys.executable,'-m','eval.run_holdout','--rehearsal','--private-dir',str(private),
             '--rehearsal-seal',str(seal),'--release','0.5a','--source-freeze-manifest',str(freeze),
             '--detector-python',str(detector),'--output',str(output)]
    if report_only:command.append('--report-only')
    return subprocess.run(command,cwd=archive,env=git.environment(),capture_output=True,timeout=1200),output


def run(output,oracle_python):
    # TemporaryDirectory is deliberately retained for private audit; no cleanup
    # of forensic evidence after a forced crash, and no real directory argument.
    root=Path(tempfile.mkdtemp(prefix='crosswire-s18-synthetic-',dir=Path(os.sep)/'tmp')).resolve();root.chmod(0o700)
    immutable=archive(root);provenance=checker_provenance(oracle_python)
    seeds,oracle_states=seed_cases(root,oracle_python)
    print(json.dumps({'phase':'synthetic oracle validated','states':oracle_states}),flush=True)
    freeze=root/'source-freeze.json'
    write(freeze,{p.relative_to(immutable).as_posix():digest(p) for p in (immutable/'src').rglob('*') if p.is_file()})
    good,good_seal=private_fixture(root,immutable,seeds,'complete')
    print(json.dumps({'phase':'synthetic complete attempt','cases':240}),flush=True)
    detector,log=wrapper(good)
    completed,public_path=invoke(immutable,good,good_seal,freeze,detector)
    if completed.returncode:
        write(root/'failure.json',{'phase':'complete','stdout':completed.stdout.decode(),'stderr':completed.stderr.decode()})
        raise RuntimeError('Synthetic complete rehearsal failed; inspect private temporary evidence')
    public=json.loads(public_path.read_text());assert_aggregate_only(public)
    assert public['micro']['precision_gate']=='provisional pass' and public['micro']['recall_gate']=='pass'
    assert public['micro']['tp']==60 and public['micro']['fp']==public['micro']['fn']==0
    assert public['repo_clustered95']['status']=='not estimable' and public['repo_clustered95']['repositories']==4
    assert all(public['by_rule'][rule]['tp']==20 and public['by_rule'][rule]['precision_gate']=='not evaluated' for rule in ('CW001','CW002','CW006'))
    assert len(log.read_text().splitlines())==240
    denied,_=invoke(immutable,good,good_seal,freeze,detector)
    assert denied.returncode==2 and len(log.read_text().splitlines())==240
    rerendered,_=invoke(immutable,good,good_seal,freeze,detector,report_only=True)
    assert rerendered.returncode==0 and len(log.read_text().splitlines())==240
    assert json.loads(public_path.read_text())==public
    broken,broken_seal=private_fixture(root,immutable,seeds,'interrupted')
    crashing,counter=wrapper(broken,kill_second=True)
    killed,_=invoke(immutable,broken,broken_seal,freeze,crashing)
    assert killed.returncode==-signal.SIGKILL
    starts=list((broken/'measurement-journal').glob('*.started.json'))
    results=list((broken/'measurement-journal').glob('*.result.json'))
    assert len(starts)==2 and len(results)==1
    denied,_=invoke(immutable,broken,broken_seal,freeze,crashing)
    assert denied.returncode==2 and len(counter.read_text().splitlines())==2
    recovered,partial=invoke(immutable,broken,broken_seal,freeze,crashing,report_only=True)
    assert recovered.returncode==0 and len(counter.read_text().splitlines())==2
    partial=json.loads(partial.read_text());assert_aggregate_only(partial)
    assert partial['status']=='interrupted' and partial['micro']=={'status':'suppressed'}
    assert partial['micro_gates']=={'precision_gate':'insufficient data','recall_gate':'insufficient data'}
    assert partial['by_rule']==partial['exclusions']=={'status':'suppressed'}
    assert partial['completed_cases']==partial['failed_cases']=={'status':'suppressed'}
    # A single small outcome hides both the cell and complementary statistics.
    unsafe=deepcopy(public);unsafe['by_rule']['CW001']['fp']=1
    unsafe['micro']['fp']=1;unsafe['micro']['precision']=60/61
    hidden=suppress_small_cells(unsafe);assert_aggregate_only(hidden)
    assert all(hidden[k]=={'status':'suppressed'} for k in ('micro','by_rule','repo_clustered95','exclusions'))
    assert hidden['micro_gates']==public['micro_gates']
    for n,correct,key in [(60,58,'micro'),(20,19,'CW001')]:
        unsafe=deepcopy(public)
        cell=unsafe['micro'] if key=='micro' else unsafe['by_rule'][key]
        cell.update(attribution_labelled=n,attribution_accuracy=correct/n)
        assert suppress_small_cells(unsafe)['micro']=={'status':'suppressed'}
    assert (good/'measurement-environment.json').stat().st_mode & 0o777==0o600
    result={'status':'pass','scope':'synthetic private fixtures only; real holdout never accessed',
            'release':'0.5a','fixtures':240,'positives':60,'controls':180,'repositories':4,
            'oracle_states_checked':oracle_states,'oracle':provenance,
            'full_attempt':{'detector_invocations':240,'tp':60,'fp':0,'fn':0,
                            'precision_verdict':'provisional pass','per_rule_verdicts':'not evaluated'},
            'forced_failure':{'mechanism':'SIGKILL from second detector child','started':2,'completed':1,
                              'detector_invocations_before_and_after_denied_rerun':2,
                              'report_only_detector_invocations':0,'public_status':'interrupted'},
            'complementary_suppression':'all linked statistical blocks withheld for a small outcome',
            'p4_checks':{'attribution_complements':'2/60 and 1/20 suppressed','categorical_micro_gates':'published outside suppressed statistics',
                         'measurement_environment':'private at claim time, not compared metadata','journal_chain':'per-row and completed-row hash verified'},
            'apparatus_sha256':apparatus(immutable),'rehearsal_driver_sha256':digest(Path(__file__)),
            'driver_timeout_seconds':1200,
            'prior_synthetic_attempt':'driver timed out at 300 seconds under concurrent T22 load; retained consumed journal, never resumed; fresh synthetic-only fixtures used',
            'fixture_location':'system temporary directory, crosswire-s18-synthetic-*; private, not committed'}
    write(output,result)
    print(json.dumps({'status':'pass','fixtures':240,'forced_failure':'no rerun; report-only verified'}))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--oracle-python',required=True)
    args=parser.parse_args();run(args.output,args.oracle_python)


if __name__=='__main__':main()
