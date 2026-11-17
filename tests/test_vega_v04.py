"""Vega V4-01..07 reproductions under PLAN v0.4 Amendment R3.

Timing budgets belong to benchmarks/perf_matrix.py, never unit-test timings.
"""
import json
import shlex

import pytest

from .test_combined import DIRECT, FALLBACK, GAP
from .test_vega_v03 import output


@pytest.mark.parametrize('mode',['pairwise','combined','plan'])
def test_v4_01_coverage_does_not_parse_unrelated_target_files(repo,monkeypatch,mode):
    from crosswire import coverage
    from crosswire.engine import analyze
    from crosswire.combined import analyze_combined
    from crosswire.planner import plan
    repo.pair({'m.py':DIRECT,'unrelated.py':'def broken(\n'}, {'m.py':DIRECT.replace('return value','return 2')},{'safe.txt':'safe\n'})
    observed=[];original=coverage._sites
    def sites(source,module,path):
        observed.append(path)
        return original(source,module,path)
    monkeypatch.setattr(coverage,'_sites',sites)
    with repo.unchanged():
        if mode=='pairwise':report=analyze(repo.path,['a','b'],target='main',cache=False)
        elif mode=='combined':report=analyze_combined(repo.path,['a','b'],'main',cache=False)
        else:report=plan(repo.path,['a','b'],'main',cache=False)
    assert 'unrelated.py' not in observed
    result=report if isinstance(report,dict) else {'coverage':report.coverage,'limitations':report.limitations}
    assert result['coverage']=='complete' and not result['limitations']


@pytest.mark.parametrize('mode',['pairwise','combined','plan'])
def test_v4_02_unchanged_unsupported_code_is_outside_coverage(repo,mode):
    irrelevant='from third_party import *\n@decorate\ndef old(args):\n    obj.method(*args)\n'
    repo.pair({'m.py':DIRECT,'unrelated.py':irrelevant},{'a.txt':'safe\n'},{'b.txt':'safe\n'})
    report,hits=output(repo,mode)
    assert not hits and report['coverage']=='complete'
    assert not report['limitations']


@pytest.mark.parametrize('mode',['pairwise','combined','plan'])
def test_v4_02_stdlib_and_third_party_references_are_not_gaps(repo,mode):
    use='from typing import Any, cast\nimport sys\nimport external_not_installed\ncast(Any, None)\nversion = sys.version\nexternal_not_installed.run()\n'
    repo.pair({}, {'a.txt':'safe\n'},{'use.py':use})
    report,hits=output(repo,mode)
    assert not hits and report['coverage']=='complete'
    assert not any(k.startswith('unknown_resolution:') for k in report['limitations'])


@pytest.mark.parametrize('mode',['pairwise','combined','plan'])
def test_v4_02_in_scope_first_party_unknown_remains_partial(repo,mode):
    repo.pair({'opaque.py':'def __getattr__(name): return 1\n'}, {'a.txt':'safe\n'},{'use.py':'import opaque\nopaque.run()\n'})
    report,hits=output(repo,mode)
    assert not hits and report['coverage']=='partial'
    assert any('open-module' in k for k in report['limitations'])


@pytest.mark.parametrize('mode',['pairwise','combined','plan'])
def test_v4_03_literal_replacement_character_is_valid_utf8_and_conflict_is_detected(repo,mode):
    repo.pair({'app/__init__.py':'','app/m.py':DIRECT},{'app/m.py':'# removed f\n'},{'app/use.py':'from app.m import f\nS = "\ufffd literal replacement char"\nf(1)\n'})
    report,hits=output(repo,mode)
    assert any(f['rule']=='CW001' and f['symbol']=='app.m.f' for f in hits)
    assert not any('utf' in k.lower() for k in report['limitations'])


def test_v4_03_actual_invalid_utf8_is_skipped_and_reported(repo):
    repo.pair({}, {'a.txt':'safe\n'},{'bad.py':b'S = "\xff"\n'})
    report,hits=output(repo)
    assert not hits and report['coverage']=='partial'
    assert any('utf' in k.lower() for k in report['limitations'])


OPEN_FORMS=[
    'from app._lazy import __getattr__\n',
    'from app._lazy import __getattr__ as __getattr__\n',
    '__getattr__ = __import__("app._lazy", fromlist=["__getattr__"]).__getattr__\n',
    'import app._lazy as lazy\n__getattr__, __dir__, __all__ = lazy.attach(__name__)\n',
    'locals().update(vars(__import__("app.impl", fromlist=["f"])))\n',
    'vars().update({"f": lambda value: value})\n',
    'exec("from app.impl import *")\n',
]


@pytest.mark.parametrize('replacement',OPEN_FORMS)
@pytest.mark.parametrize('mode',['pairwise','combined','plan'])
def test_v4_04_module_namespace_binding_forms_are_open_never_removals(repo,mode,replacement):
    lazy='from .impl import f\ndef __getattr__(name): return f\ndef attach(name): return __getattr__, lambda: [], ["f"]\n'
    repo.pair({'app/__init__.py':'','app/m.py':DIRECT,'app/impl.py':DIRECT,'app/_lazy.py':lazy}, {'app/m.py':replacement},{'app/use.py':'from app.m import f\nf(1)\n'})
    report,hits=output(repo,mode)
    assert not [f for f in hits if f['rule'] in {'CW001','CW002','CW006'}]
    assert report['coverage']=='partial'
    assert any('open-module' in k for k in report['limitations'])


@pytest.mark.parametrize('case',['inexact','branch-location'])
def test_v4_05_finding_caveats_are_populated_and_survive_sarif(repo,case):
    if case=='inexact':
        source=''.join(f'value_{i} = 0\n'+GAP for i in range(7))
        nodes={f'A{i}':('target',{'same.py':source.replace(f'value_{i} = 0',f'value_{i} = 1')}) for i in range(7)}
        nodes['X']=('target',{'same.py':source.replace('value_0 = 0','value_0 = 2')})
        repo.named_dag({'same.py':source},nodes);branches=tuple(nodes)
    else:
        original='import m\n'+GAP+'# caller additions below\n'
        repo.named_dag({'m.py':DIRECT,'use.py':original},{'A':('target',{'m.py':'# removed\n','use.py':None,'renamed_use.py':original}),'C':('target',{'use.py':original+'m.f(1)\n'})});branches=('A','C')
    report,hits=output(repo,branches=branches)
    hit=next(f for f in hits if (not f['culprits_exact'] if case=='inexact' else f['location']=='branch'))
    assert hit['limitations'] and all(isinstance(x,str) and x for x in hit['limitations'])
    caveat=' '.join(hit['limitations']).lower()
    assert ('culprit' in caveat and ('bound' in caveat or 'exact' in caveat or 'minimal' in caveat)) if case=='inexact' else ('branch' in caveat and ('location' in caveat or 'tip' in caveat))
    result=repo.check('--target','main','--combined','--format','sarif',branches=branches)
    assert result.returncode==1,result.stderr
    entries=json.loads(result.stdout)['runs'][0]['results']
    matching=[r for r in entries if r['ruleId']==hit['rule'] and r['properties'].get('limitations')==hit['limitations']]
    assert matching


@pytest.mark.parametrize('mode',['pairwise','combined','plan'])
def test_v4_06_all_modes_keep_the_same_evidenced_rename_hint(repo,mode):
    original='def charge(value):\n    return value\n'
    repo.pair({'billing.py':original},{'billing.py':original.replace('charge(','create_charge(')},{'refunds.py':'from billing import charge\ncharge(1)\n'})
    _,hits=output(repo,mode)
    hit=next(f for f in hits if f['rule']=='CW001' and f['symbol']=='billing.charge')
    assert hit['hint']=='use `billing.create_charge`'


@pytest.mark.parametrize('order',[('caller','decoy','remove'),('remove','caller','decoy')])
def test_v4_07_repro_keeps_repo_spelling_and_original_order(repo,order):
    repo.named_dag({'m.py':DIRECT},{'remove':('target',{'m.py':'# removed\n'}),'caller':('target',{'use.py':'import m\nm.f(1)\n'}),'decoy':('target',{'safe.txt':'safe\n'})})
    spelling=repo.path.name+'/../'+repo.path.name
    result=repo.cli('check','--repo',spelling,'--target','main','--combined','--format','json',*order,cwd=repo.path.parent)
    assert result.returncode==1,result.stderr
    hit=next(f for f in json.loads(result.stdout)['findings'] if f['rule']=='CW001')
    args=shlex.split(hit['repro'])
    assert args[args.index('--repo')+1]==spelling
    assert args[-2:]==[b for b in order if b!='decoy']
    repeated=repo.cli(*args[1:],'--format','json',cwd=repo.path.parent)
    assert repeated.returncode==1,repeated.stderr
    assert any(f['rule']==hit['rule'] and f['symbol']==hit['symbol'] and f['culprits']==hit['culprits'] for f in json.loads(repeated.stdout)['findings'])


def test_v4_07_absolute_repo_repro_runs_from_unrelated_cwd_in_nway_order(repo,tmp_path):
    source=DIRECT+GAP+FALLBACK
    repo.named_dag({'m.py':source,'fast.py':DIRECT},{'A':('target',{'m.py':source.replace(DIRECT,'# direct removed\n',1)}),'B':('target',{'m.py':source.replace(FALLBACK,'# fallback removed\n')}),'C':('target',{'use.py':'import m\nm.f(1)\n'}),'D':('target',{'safe.txt':'safe\n'})})
    _,hits=output(repo,branches=('D','C','B','A'))
    hit=next(f for f in hits if f['rule']=='CW006');args=shlex.split(hit['repro'])
    assert args[args.index('--repo')+1]==str(repo.path)
    assert args[-3:]==['C','B','A']
    foreign=tmp_path/'unrelated';foreign.mkdir()
    result=repo.cli(*args[1:],'--format','json',cwd=foreign)
    assert result.returncode==1,result.stderr
    assert any(f['rule']=='CW006' and f['culprits']==['A','B'] for f in json.loads(result.stdout)['findings'])


def test_v4_07_repo_option_is_omitted_when_not_supplied(repo):
    repo.pair({'m.py':DIRECT},{'m.py':'# removed\n'},{'use.py':'import m\nm.f(1)\n'})
    result=repo.cli('check','--target','main','--combined','--format','json','a','b',cwd=repo.path)
    assert result.returncode==1,result.stderr
    hit=next(f for f in json.loads(result.stdout)['findings'] if f['rule']=='CW001')
    assert '--repo' not in shlex.split(hit['repro'])
