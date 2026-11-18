"""Go S16 fixtures; CI requires the pinned compiler and runs a fast subset."""
from copy import deepcopy
import json
import os
import shutil
from pathlib import Path
import subprocess

import pytest

from conformance import git,go_oracle,go_run
from conformance.oracle import KitBug
from conformance.render.go import NoCounterpart,render,MODULE

CASES=go_run.load_cases()
GO=shutil.which('go')
CI_CASES=('rename-conflict','move_module-conflict','arity-conflict','arity-control',
          'go4-same-file-conflict','go4-cross-file-conflict','go4-method-conflict',
          'go4-duplicate-import-conflict')


def require_go(binary):
    if binary is None:
        if os.environ.get('CROSSWIRE_REQUIRE_GO')=='1':
            pytest.fail('CROSSWIRE_REQUIRE_GO=1 requires Go 1.27.1 on PATH')
        pytest.skip('Go absent locally; pinned Go 1.27.1 required for compiler checks')
    return binary


@pytest.fixture
def go_binary():return require_go(GO)


def named(name):return next(item for item in CASES if item[2]['id']==name)


@pytest.mark.parametrize('item',CASES,ids=[item[2]['id'] for item in CASES])
def test_render_deterministic_neutral_and_explicit_counterparts(item):
    _,template,case=item;before=deepcopy(template)
    if template['contracts']['go']['id'] is None:
        with pytest.raises(NoCounterpart):render(template,case)
    else:
        result=render(template,case)
        assert result==render(template,case) and template==before
        assert result['base']['go.mod']==f'module {MODULE}\n\ngo 1.27.1\n'.encode()
        assert all(p=='go.mod' or p.endswith('.go') and not p.endswith('_test.go') for p in result['base'])


def test_category_helper_reuses_s19a_bytes_and_frozen_go4_mapping():
    root=Path(__file__).parents[1]
    assert (root/'conformance/go_categories.go').read_bytes()==(root/'benchmarks/s19a_categories.go').read_bytes()
    assert 'DuplicateDecl' in go_oracle.DUPLICATES


def test_sources_and_native_commit_ids_are_deterministic(tmp_path):
    _,template,case=named('go4-duplicate-import-conflict');rendered=render(template,case);values=[]
    for name in ('one','two'):
        repo=tmp_path/name;target,tips=git.build(repo,rendered)
        final=git.integrate(repo,target,tips,list(tips));values.append((target,tips,final,git.files_at(repo,final)))
    assert values[0]==values[1]


def test_oracle_environment_ignores_user_go_context(tmp_path,monkeypatch):
    monkeypatch.setenv('GOFLAGS','-tags=unexpected');monkeypatch.setenv('GOWORK','unexpected')
    env=go_oracle.environment(tmp_path)
    for k,v in {'GOFLAGS':'-mod=readonly','GOTOOLCHAIN':'local','GOENV':'off','GOWORK':'off','CGO_ENABLED':'0','GOPROXY':'off','GOSUMDB':'off','GOVCS':'*:off'}.items():assert env[k]==v
    assert env['GOCACHE']==str(tmp_path/'gocache') and env['GOOS']=='darwin' and env['GOARCH']=='arm64'


def test_wrong_go_version_is_a_kit_bug_before_helper_build(tmp_path,monkeypatch):
    calls=[]
    def fake(self,args,*a,**kw):
        calls.append(args);return subprocess.CompletedProcess(args,0,json.dumps({'GOVERSION':'go0.0'}).encode(),b'')
    monkeypatch.setattr(go_oracle.GoOracle,'execute',fake)
    with pytest.raises(KitBug,match='must be go1.27.1'):go_oracle.GoOracle('go',tmp_path/'cache')
    assert len(calls)==1


def test_template_oracle_disagreement_cannot_certify_case():
    _,template,case=named('rename-conflict')
    observations={name:{'verdict':'valid','diagnostics':[]} for name in ('target','A','B','A+B')}
    with pytest.raises(KitBug,match='Oracle/template disagreement'):
        go_oracle.validate(template,case,observations,render(template,case))


def test_no_counterpart_cannot_be_a_detector_pass(tmp_path):
    path,template,case=named('conjunctive-conflict')
    result=go_run.run_case(path,template,case,tmp_path/'case',None)
    assert result['status']=='no Go counterpart' and result['detector']=='not available'
    assert not (tmp_path/'case/oracle.json').exists()


def test_go_oracle_kit_no_detector_pass(tmp_path,monkeypatch,go_binary):
    from conformance import run
    monkeypatch.setattr(run,"invoke_detector",lambda *a,**kw:pytest.fail("Go detector is unavailable"))
    output=tmp_path/'kit'
    required=os.environ.get('CROSSWIRE_REQUIRE_GO')=='1'
    selection=[arg for case in CI_CASES for arg in ('--case',case)] if required else []
    code=go_run.main(['--go',go_binary,'--output',str(output),*selection])
    summary=json.loads((output/'summary.json').read_text())
    assert code==0,(summary.get('reason'),[(r['id'],r.get('reason')) for r in summary['cases'] if r['status']=='kit-bug'])
    assert summary['status']=='oracle verified; detector not available'
    assert summary['detector']=='not available' and summary['mode_checks']==0
    assert summary['selection']==('partial' if required else 'full')
    assert summary['case_count']==(8 if required else 34)
    assert summary['no_counterpart']==(0 if required else 6)
    assert summary['oracle_states']==(32 if required else 120)
    if required:assert {row['id'] for row in summary['cases']}==set(CI_CASES)
    for row in summary['cases']:
        assert row['detector']=='not available' and row['status']!='pass'


def test_missing_go_fails_when_required_in_ci(monkeypatch):
    monkeypatch.setenv('CROSSWIRE_REQUIRE_GO','1')
    with pytest.raises(pytest.fail.Exception,match='requires Go 1.27.1'):
        require_go(None)


def test_missing_go_skips_locally(monkeypatch):
    monkeypatch.delenv('CROSSWIRE_REQUIRE_GO',raising=False)
    with pytest.raises(pytest.skip.Exception,match='Go absent locally'):
        require_go(None)


def test_missing_subset_is_a_kit_bug():
    _,template,case=named('rename-conflict')
    with pytest.raises(KitBug,match='Missing declared'):
        go_oracle.validate(template,case,{},render(template,case))


def test_go4_unrelated_declaration_position_is_a_kit_bug():
    _,template,case=named('go4-method-conflict')
    observation={'verdict':'valid','diagnostics':[]}
    states={s:deepcopy(observation) for s in ('target','A','B','A+B')}
    states['A+B']={'verdict':'broken','declaration_locations':{'a':{'path':'api/alpha.go','line':2,'column':10},'b':{'path':'api/beta.go','line':2,'column':10}},
      'diagnostics':[{'compiler_position_match':True,'contract':'GO-4','category':'DuplicateMethod','path':'api/beta.go','line':99,'column':10}]}
    with pytest.raises(KitBug,match='Unrelated Go declaration'):
        go_oracle.validate(template,case,states,render(template,case))


def test_go4_english_message_does_not_decide_category():
    _,template,case=named('go4-method-conflict')
    states={s:{'verdict':'valid','diagnostics':[]} for s in ('target','A','B','A+B')}
    states['A+B']={'verdict':'broken','declaration_locations':{'a':{'path':'api/alpha.go','line':2,'column':10},'b':{'path':'api/beta.go','line':2,'column':10}},
      'diagnostics':[{'compiler_position_match':True,'contract':'GO-4','category':'DuplicateMethod','message':'arbitrary unrelated words','path':'api/beta.go','line':2,'column':10}]}
    assert go_oracle.validate(template,case,states,render(template,case))['combined']=='broken'
