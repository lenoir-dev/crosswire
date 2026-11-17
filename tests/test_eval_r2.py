"""Accepted E4 apparatus findings: synthetic evidence, never private cases."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from eval.measure import diagnostics_for, evaluate, report
from eval.metrics import aggregate, clustered, match
from eval.integrity import assert_case, repository_hash
from eval.oracle import scope
from eval.run_holdout import assert_aggregate_only, suppress_small_cells


@pytest.fixture
def labelled(repo):
    consumer='import m\nm.f(1)\n'
    commits=repo.named_dag({'m.py':'def f(value): return value\n'}, {'A':('target',{'m.py':'def f(value, *, extra): return value\n'}),'B':('target',{'use.py':consumer})})
    tree=repo.git('merge-tree','--write-tree','A','B').stdout.decode().splitlines()[0]
    merged=repo.git('commit-tree',tree,'-p',commits['A'],'-p',commits['B'],'-m','independent native integration').stdout.decode().strip()
    repo.checkout(merged)
    error={'file':str(repo.path/'use.py'),'range':{'start':{'line':1,'character':0}},'rule':'reportCallIssue','message':'Argument missing for parameter extra'}
    return {'repository':'synthetic','path':str(repo.path),'eligible':True,'target':commits['target'],'tips':{k:commits[k] for k in ['A','B']},'integrated':merged,'kind':'positive','family':'required_keyword','type':'PY-4','symbol':'m.f','consumer':'use.py','consumer_source':consumer,'roots':['m.py'],'oracle_positive':True,'oracle':{'integrated':{'diagnostics':[error]}}}


def shim(tmp_path, stdout='', code=0):
    path=tmp_path/'detector-shim'
    path.write_text(f'#!{sys.executable}\nimport sys\nprint({stdout!r})\nsys.exit({code})\n')
    path.chmod(0o755)
    return str(path)


@pytest.mark.parametrize('stdout,code',[('',2),('Traceback: failure',1),('{}',0),('[]',0)])
def test_e4_05_detector_failures_remain_false_negatives(labelled,tmp_path,stdout,code):
    row=evaluate(labelled,shim(tmp_path,stdout,code),tmp_path)
    assert row['eligible'] and row['fn']==1 and row['detector_failure']
    assert report([row])['micro']['detector_errors']==1
    assert report([row])['micro']['recall']==0


def test_e4_05_timeout_is_a_failure_row(labelled,tmp_path,monkeypatch):
    original=subprocess.run
    def run(args,*a,**kw):
        if 'crosswire' in args:raise subprocess.TimeoutExpired(args,60)
        return original(args,*a,**kw)
    monkeypatch.setattr(subprocess,'run',run)
    row=evaluate(labelled,sys.executable,tmp_path)
    assert row['detector_failure']=='timeout' and row['fn']==1 and row['eligible']


def test_e4_06_wrong_emitted_rule_is_fp_and_fn_in_different_buckets(labelled,tmp_path):
    finding={'rule':'CW001','symbol':'m.f','path':'use.py','line':2,'message':'removed','branch':'B','culprits':['A']}
    row=evaluate(labelled,shim(tmp_path,json.dumps({'findings':[finding]})),tmp_path)
    assert (row['tp'],row['fp'],row['fn'])==(0,1,1)
    result=report([row])
    assert result['by_rule']['CW001']['fp']==1
    assert result['by_rule']['CW002']['fn']==1
    assert result['by_rule']['CW001']['fn']==0


def test_e4_09_missing_module_matches_use_file_and_module_only():
    diagnostic={'type':'PY-2','path':'use.py','module':'pkg.m','symbol':None,'occurrence':'import'}
    prediction={**diagnostic,'rule':'CW001','symbol':'pkg.m.f','occurrence':'later-call'}
    assert match([prediction],[diagnostic])['tp']==1
    assert match([{**prediction,'module':'pkg.other'}],[diagnostic])['tp']==0
    assert match([prediction,prediction],[diagnostic])['fp']==1


def test_e4_13_all_categories_at_one_call_are_used(labelled):
    error=labelled['oracle']['integrated']['diagnostics'][0]
    labelled['oracle']['integrated']['diagnostics'].append({**error,'message':'No parameter named old'})
    diagnostics=diagnostics_for(labelled)
    assert len(diagnostics)==1
    assert set(diagnostics[0]['reasons'])=={'missing','unknown keyword'}
    result=match([{**diagnostics[0],'rule':'CW002','reason':'unknown keyword'}],diagnostics)
    assert result['tp']==1 and not result['reason_mismatches']


def test_e4_13_different_attributable_calls_are_not_discarded(labelled):
    labelled['consumer_source']+='m.f(2)\n'
    error=labelled['oracle']['integrated']['diagnostics'][0]
    labelled['oracle']['integrated']['diagnostics'].append({**error,'range':{'start':{'line':2,'character':0}}})
    assert len(diagnostics_for(labelled))==2


def test_e4_07_scope_includes_nested_tests(tmp_path):
    for path in ['pkg','tests','other/test']:(tmp_path/path).mkdir(parents=True)
    assert set(scope(tmp_path,['pkg']))=={'pkg','tests','other/test'}


def test_e4_04_integrity_detects_worktree_ref_and_added_file(labelled,repo):
    assert_case(labelled)
    sealed=repository_hash(repo.path)
    repo.write('m.py','changed\n')
    with pytest.raises(AssertionError,match='worktree'):assert_case(labelled)
    assert repository_hash(repo.path)!=sealed
    repo.write('m.py','def f(value, *, extra): return value\n')
    repo.git('update-ref','refs/heads/A',labelled['target'])
    with pytest.raises(AssertionError,match='tip'):assert_case(labelled)


def test_e4_11_bootstrap_needs_five_eligible_repositories_and_stricter_bound():
    assert clustered([{'repository':str(i),'eligible':True,'tp':20} for i in range(4)])['status']=='not estimable'
    rows=[{'repository':'good','eligible':True,'tp':1000}]+[{'repository':str(i),'eligible':True,'fp':1} for i in range(4)]
    result=aggregate(rows)
    assert result['precision']>.99 and result['precision_wilson95'][0]>.9
    assert result['precision_gate_lower_bound']<.9 and result['precision_gate']=='fail'


@pytest.mark.parametrize('payload',[{'exclusions':{'github.com/private/repo':5}},{'exclusions':{'unknown-private-reason':5}},{'status':'/private/case'},{'rows':[]}])
def test_e4_12_guard_checks_dynamic_keys_and_values(payload):
    with pytest.raises(AssertionError):assert_aggregate_only(payload)


def test_e4_12_small_cells_are_suppressed():
    assert suppress_small_cells({'tp':6,'fp':1,'fn':0})=={'status':'suppressed'}
    assert suppress_small_cells({'tp':0,'fp':0,'fn':0})=={'status':'suppressed'}


def test_e4_03_v04_runner_refuses_measurement_without_opening_private_data(tmp_path):
    result=subprocess.run([sys.executable,'-m','eval.run_holdout','--private-dir',str(tmp_path)],capture_output=True,text=True)
    assert result.returncode==2 and 'prohibits holdout measurement' in result.stderr
    assert list(tmp_path.iterdir())==[]


def test_e4_01_no_public_screening_catalog():
    import eval.screen
    assert not hasattr(eval.screen,'CANDIDATES')


def test_e4_14_builder_does_not_mutate_parent_environment(repo,tmp_path):
    from eval.corpus import create_repo
    before=dict(os.environ)
    repo.write('m.py','value = 1\n')
    sha=repo.commit('upstream')
    create_repo({'path':str(repo.path),'sha':sha},tmp_path/'exported')
    assert dict(os.environ)==before


def test_e4_14_dependency_lock_contains_hash_for_every_pinned_distribution():
    lock=Path('docs/validation/v04-oracle-requirements.lock').read_text()
    requirements=Path('docs/validation/v04-oracle-requirements.txt').read_text().splitlines()
    for line in requirements:
        assert line+' \\\n    --hash=sha256:' in lock


def test_m1_identical_calls_at_distinct_occurrences_do_not_collapse():
    from eval.oracle import occurrence
    source='import m\nm.f(1)\nm.f(1)\n'
    assert occurrence(source,2,'m.f')!=occurrence(source,3,'m.f')


def test_e4_07_supported_test_diagnostic_is_in_recall(labelled,repo):
    source='import m\nm.f(2)\n'
    repo.write('tests/test_use.py',source)
    labelled['integrated']=repo.commit('supported test consumer')
    error=labelled['oracle']['integrated']['diagnostics'][0]
    labelled['oracle']['integrated']['diagnostics'].append({**error,'file':str(repo.path/'tests/test_use.py')})
    assert {d['path'] for d in diagnostics_for(labelled)}=={'use.py','tests/test_use.py'}


def test_e4_12_small_exclusion_counts_are_suppressed():
    assert suppress_small_cells({'exclusions':{'oracle-ineligible':2}})=={'exclusions':{'oracle-ineligible':'suppressed'}}


def test_e4_05_malformed_finding_is_failure_not_global_abort(labelled,tmp_path):
    row=evaluate(labelled,shim(tmp_path,json.dumps({'findings':[{'rule':'CW001'}]})),tmp_path)
    assert row['detector_failure']=='invalid-output' and row['fn']==1


def test_e4_14_git_diff_retains_patch_terminator(repo):
    from eval.corpus import git
    repo.pair({'m.py':'old = 1\n'},{'m.py':'new = 2\n'},{'b.txt':'safe\n'})
    patch=git(repo.path,'diff','main','a')
    assert patch.endswith('\n')
    result=subprocess.run(['git','apply','--check','-'],cwd=repo.path,env=repo.env,input=patch,text=True,capture_output=True)
    assert result.returncode==0,result.stderr


def test_e4_06_unlabelled_predictions_remain_in_the_emitted_rule_bucket():
    row={'repository':'synthetic','eligible':True,'tp':0,'fp':0,'fn':0,'by_rule':{},'unlabelled_predictions':[{'finding':{'rule':'CW001'}}]}
    summary=report([row])
    assert summary['micro']['unlabelled_predictions']==1
    assert summary['by_rule']['CW001']['unlabelled_predictions']==1
    assert summary['by_rule']['CW002']['unlabelled_predictions']==0
    assert summary['by_rule']['CW006']['unlabelled_predictions']==0


def test_e4_05_non_utf8_detector_output_is_a_failure_row(labelled,tmp_path):
    path=tmp_path/'binary-detector'
    path.write_text(f'#!{sys.executable}\nimport sys\nsys.stdout.buffer.write(bytes([255]))\n')
    path.chmod(0o755)
    row=evaluate(labelled,str(path),tmp_path)
    assert row['detector_failure']=='invalid-output' and row['fn']==1


def test_e4_14_checker_engine_tree_hash_binds_sources_and_stub_files(tmp_path):
    from eval.toolchain import tree_digest
    (tmp_path/'index.js').write_text('checker engine\n')
    (tmp_path/'typeshed').mkdir()
    stub=tmp_path/'typeshed/builtins.pyi';stub.write_text('class object: ...\n')
    before=tree_digest(tmp_path)
    assert before==tree_digest(tmp_path)
    stub.write_text('class object: changed\n')
    assert tree_digest(tmp_path)!=before
    pins=json.loads(Path('eval/toolchain.json').read_text())
    assert len(pins['pyright']['npm_tree_sha256'])==64


@pytest.mark.parametrize('family,variant,negative',[('class_remove',4,'submodule_reexport'),('required_keyword',5,'same_name_other_module')])
def test_e4_08_hard_negatives_make_the_advertised_api_edit(repo,tmp_path,family,variant,negative):
    from eval.families import build
    from eval.corpus import git
    from eval.runtime import smoke
    repo.write('upstream_pkg/__init__.py','')
    repo.write('upstream_pkg/api.py','def real_api(value): return value\n')
    sha=repo.commit('real fixture API')
    data={'version':'1.1.407','summary':{'filesAnalyzed':3,'errorCount':0},'generalDiagnostics':[]}
    checker=shim(tmp_path,json.dumps(data))
    row=build({'path':str(repo.path),'sha':sha,'repository':'synthetic','roots':['upstream_pkg']},tmp_path/'negative',family,'compatible',variant,sys.executable,checker)
    assert row['eligible'] and row['hard_negative']==negative
    directory=Path(row['path']);package=f'crosswire_probe_{variant:03d}'
    api=f'{package}/api.py'
    assert git(directory,'show',f"{row['target']}:{api}")==git(directory,'show',f"A:{api}")
    if negative=='submodule_reexport':
        path=f'{package}/__init__.py'
        assert 'from . import api' in git(directory,'show',f"{row['target']}:{path}")
        assert git(directory,'show',f'A:{path}')==''
    else:
        path=f'{package}/other.py'
        assert 'def f(' in git(directory,'show',f"{row['target']}:{path}")
        assert 'def f(' not in git(directory,'show',f'A:{path}')
    assert all(v['status']=='pass' for v in smoke(row,sys.executable).values())
