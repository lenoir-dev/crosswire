"""Independent reproductions of every accepted Vega V3 finding (R1)."""
import json
import pytest
from .test_combined import DIRECT, GAP


def output(repo, mode='combined', branches=('a','b')):
    if mode=='plan':
        result=repo.cli('plan','--repo',str(repo.path),'--target','main','--format','json',*branches)
    else:
        options=['--target','main','--combined'] if mode=='combined' else []
        result=repo.check(*options,'--format','json',branches=branches)
    assert result.returncode in (0,1),result.stderr
    report=json.loads(result.stdout)
    return report, ([f for item in report['blocked'] for f in item['findings']] if mode=='plan' else report['findings'])


@pytest.mark.parametrize('mode',['pairwise','combined','plan'])
@pytest.mark.parametrize('malformed',['value = '+'+'.join(['1']*600)+'\n','value = "\x00"\n'])
def test_v3_01_parse_failure_is_a_gap_not_traceback(repo,mode,malformed):
    repo.pair({'m.py':DIRECT},{'a.txt':'safe\n'},{'generated.py':malformed})
    report,hits=output(repo,mode)
    assert not [f for f in hits if f['severity']=='error']
    assert report['coverage']=='partial'
    assert any('parse' in key or 'binary' in key for key in report['limitations'])


@pytest.mark.parametrize('mode',['pairwise','combined','plan'])
@pytest.mark.parametrize('replacement',[
 'from app.impl import *\n',
 'try:\n    from app.impl import *\nexcept ImportError:\n    pass\n',
])
def test_v3_02_star_exports_are_open_never_removed(repo,mode,replacement):
    repo.pair({'app/__init__.py':'','app/m.py':DIRECT,'app/impl.py':DIRECT},{'app/m.py':replacement},{'app/use.py':'from app.m import f\nf(1)\n'})
    report,hits=output(repo,mode)
    assert not [f for f in hits if f['rule'] in {'CW001','CW002','CW006'}]
    assert 'open-module' in report['limitations']


@pytest.mark.parametrize('replacement',[
 'from typing import Any\ndef __getattr__(name: str) -> Any:\n    return 1\n',
 'from app.impl import f as other\nglobals().update(f=other)\n',
 'import sys\nfrom app.impl import f as other\nsetattr(sys.modules[__name__], "f", other)\n',
])
def test_v3_03_dynamic_exports_are_open(repo,replacement):
    repo.pair({'app/__init__.py':'','app/m.py':DIRECT,'app/impl.py':DIRECT},{'app/m.py':replacement},{'app/use.py':'from app.m import f\nf(1)\n'})
    for mode in ('pairwise','combined','plan'):
        report,hits=output(repo,mode)
        assert not [f for f in hits if f['rule'] in {'CW001','CW006'}]
        assert 'open-module' in report['limitations']


def test_v3_04_target_break_is_attributed_to_target(repo):
    repo.named_dag({'app/__init__.py':'','app/m.py':DIRECT+GAP+'def g(): return 1\n'}, {
        'a':('target',{'app/use.py':'from app.m import f\nf(1)\n'}),
        'b':('target',{'app/m.py':DIRECT+GAP+'def g(): return 2\n'})})
    repo.checkout('main');repo.write('app/m.py','# removed\n'+GAP+'def g(): return 1\n');repo.commit('target removes f')
    report,hits=output(repo)
    hit=next(f for f in hits if f['rule']=='CW001')
    assert hit['culprits']==['main'] and hit['culprits_exact'] is True
    assert 'main' in hit['message'] and hit['hint']=='rebase a onto main'
    assert report['coverage']!='bounded' and report['limits']['hit']==[]


def test_v3_05_target_reference_work_is_restricted_to_changed_modules(repo,monkeypatch):
    from crosswire.engine import _Analysis
    from crosswire.planner import plan
    base={f'unrelated_{i}.py':'import external\nexternal.call()\n' for i in range(30)}
    base['m.py']=DIRECT
    repo.named_dag(base,{'a':('target',{'m.py':DIRECT.replace('return value','return 2')}),'b':('target',{'b.txt':'safe\n'})})
    calls=[];original=_Analysis.references
    def references(self,sha,path,*args,**kwargs):
        calls.append(path)
        return original(self,sha,path,*args,**kwargs)
    monkeypatch.setattr(_Analysis,'references',references)
    with repo.unchanged():plan(repo.path,['a','b'],'main',cache=False)
    from collections import Counter
    assert max(Counter(p for p in calls if p.startswith('unrelated_')).values(), default=0) <= 1, 'T10 permits one target index pass, never rescans per integrated state'


def test_v3_06_package_submodule_is_resolved_in_combined(repo):
    repo.pair({'app/__init__.py':'from . import util\n','app/util.py':'def h(): return 1\n'}, {'app/__init__.py':'','app/util.py':None},{'app/use.py':'from app import util\nutil.h()\n'})
    _,hits=output(repo)
    assert any(f['rule']=='CW001' and f['symbol'].startswith('app.util') for f in hits)


def test_v3_07_module_becomes_package_without_removal(repo):
    repo.pair({'app/__init__.py':'','app/m.py':DIRECT},{'app/m.py':None,'app/m/__init__.py':DIRECT},{'app/use.py':'from app.m import f\nf(1)\n'})
    for mode in ('pairwise','combined'):
        _,hits=output(repo,mode)
        assert not [f for f in hits if f['rule']=='CW001']


def test_v3_08_submodule_still_importable_without_init_reexport(repo):
    repo.pair({'app/__init__.py':'from . import util\n','app/util.py':'def h(): return 1\n'}, {'app/__init__.py':''},{'app/use.py':'from app import util\nutil.h()\n'})
    for mode in ('pairwise','combined'):
        _,hits=output(repo,mode)
        assert not [f for f in hits if f['rule']=='CW001']


def test_v3_09_target_textual_conflict_is_exact_without_spurious_limits(repo):
    repo.pair({'x.py':'value = 1\n'},{'x.py':'value = 2\n'},{'safe.txt':'safe\n'})
    repo.checkout('main');repo.write('x.py','value = 3\n');repo.commit('advance target')
    report,hits=output(repo)
    hit=next(f for f in hits if f['rule']=='CW005')
    assert hit['culprits']==['main'] and hit['culprits_exact']
    assert report['coverage']!='bounded' and report['limits']['hit']==[]


def test_v3_10_stacked_use_is_attributed_to_earliest_branch_once(repo):
    repo.named_dag({'m.py':DIRECT},{'A':('target',{'use.py':'import m\nm.f(1)\n'}),'B':('A',{'b.txt':'safe\n'}),'rm':('target',{'m.py':'# removed\n'})})
    _,hits=output(repo,branches=('rm','B','A'))
    matching=[f for f in hits if f['rule']=='CW001' and f['path']=='use.py']
    assert len(matching)==1 and matching[0]['branch']=='A'


def test_v3_11_migration_culprits_exclude_noncolliding_branch(repo):
    from crosswire.integrate import integrate
    from crosswire.planner import _migration_findings
    commits=repo.named_dag({}, {'M1':('target',{'app/migrations/0002_a.py':''}),'M2':('target',{'app/migrations/0002_b.py':''}),'M3':('target',{'app/migrations/0003_c.py':''})})
    with repo.unchanged():
        state=integrate(repo.path,commits['target'],[(b,commits[b]) for b in ('M1','M2','M3')])
        # Public plan blocked findings can omit branches not yet integrated. Exercise the exact state reproduction too.
        hits=_migration_findings(repo.path,commits['target'],state.commit,('M1','M2','M3'))
    assert hits
    for hit in hits:
        assert 'M3' not in hit.culprits
        assert set(hit.culprits)|{hit.branch}=={'M1','M2'}


def test_v3_12_summary_stores_only_real_migrations(repo):
    from crosswire.engine import summarize
    repo.pair({}, {'ordinary.py':'value = 1\n','app/migrations/0002_add.py':'','db/versions/a.py':"revision = 'a'\ndown_revision = 'base'\n"},{'b.txt':'safe\n'})
    summary=summarize(repo.path,'a',repo.git('rev-parse','a').stdout.decode().strip(),repo.git('rev-parse','main').stdout.decode().strip(),('.',))
    assert set(summary.migrations)=={'app/migrations/0002_add.py','db/versions/a.py'}


def test_v3_13_unknown_references_are_visible_coverage_gaps(repo):
    repo.pair({'m.py':DIRECT,'opaque.py':'def __getattr__(name): return 1\n'},{'a.txt':'safe\n'},{'use.py':'import opaque\nopaque.call()\n'})
    report,hits=output(repo)
    assert not [f for f in hits if f['severity']=='error']
    assert report['coverage']=='partial'
    assert any('open-module' in key and value['count']>=1 for key,value in report['limitations'].items())


@pytest.mark.parametrize('error',[SyntaxError,RecursionError,ValueError,MemoryError])
def test_v3_01_all_declared_parse_failures_are_unknown_at_choke_points(monkeypatch,error):
    import ast
    from crosswire.state import _build_module_data
    from crosswire.python_analyzer import _reference_data
    def fail(*args,**kwargs):raise error('synthetic parse failure')
    with monkeypatch.context() as patch:
        patch.setattr(ast,'parse',fail)
        module=_build_module_data('value = 1\n','parse_case','parse_case.py')
        references=_reference_data('import dependency\n',error.__name__,'parse_case.py',False)
    assert module is None and references is None


def test_v3_01_unexpected_cli_exception_has_exit_two_and_no_traceback(monkeypatch,capsys):
    from crosswire import cli
    def fail(*args,**kwargs):raise RuntimeError('independent regression')
    monkeypatch.setattr(cli,'_main',fail)
    assert cli.main([])==2
    captured=capsys.readouterr()
    assert captured.out==''
    assert captured.err=='crosswire: error: internal error: RuntimeError: independent regression\n'
