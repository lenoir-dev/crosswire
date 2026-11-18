"""BF1: Vega v0.5-mut-vega.md section 3; imported binding versus local class."""
import pytest
from crosswire.engine import analyze
from crosswire.combined import analyze_combined
from crosswire.planner import plan


def build(repo,form,external):
    source='from unittest import TestCase\n' if external else 'class TestCase:\n    pass\n'
    consumer='import pkg\npkg.TestCase\n' if form=='attribute' else 'from pkg import TestCase\n'
    repo.named_dag({'pkg.py':source},
        {'A':('target',{'pkg.py':None,'pkg_moved.py':source}),
         'B':('target',{'consumer.py':consumer})})


def observed(repo,mode):
    with repo.unchanged():
        if mode=='pairwise':
            report=analyze(repo.path,['A','B'],target='main',cache=False)
            return [(f.rule,f.path,f.symbol) for f in report.findings if f.severity=='error']
        if mode=='combined':
            report=analyze_combined(repo.path,['A','B'],'main',cache=False)
            return [(f.rule,f.path,f.symbol) for f in report.findings if f.severity=='error']
        report=plan(repo.path,['A','B'],'main',cache=False)
        return [(f['rule'],f['path'],f['symbol']) for b in report['blocked'] for f in b['findings'] if f['severity']=='error']


@pytest.mark.parametrize('form',['attribute','from-import'])
def test_pairwise_finds_imported_reexport_module_move(repo,form):
    build(repo,form,True)
    assert observed(repo,'pairwise')==[('CW001','consumer.py','pkg.TestCase')]


@pytest.mark.parametrize('form',['attribute','from-import'])
@pytest.mark.parametrize('mode',['combined','plan'])
@pytest.mark.xfail(strict=True,raises=AssertionError,reason='BF1: imported unittest.TestCase re-export is discarded by combined tip-validity gate before removed-module check; Vega v0.5-mut-vega.md section 3')
def test_bf1_combined_plan_find_imported_reexport_module_move(repo,form,mode):
    build(repo,form,True)
    assert observed(repo,mode)==[('CW001','consumer.py','pkg.TestCase')]


@pytest.mark.parametrize('form',['attribute','from-import'])
@pytest.mark.parametrize('mode',['pairwise','combined','plan'])
def test_control_locally_defined_binding_is_found(repo,form,mode):
    build(repo,form,False)
    assert observed(repo,mode)==[('CW001','consumer.py','pkg.TestCase')]
