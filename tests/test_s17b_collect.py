"""Collector orchestration with entirely synthetic injected clients/selectors."""
from types import SimpleNamespace

from benchmarks.s17b import collect
from benchmarks.s17b.selection import Ceiling


def test_global_order_and_selected_cap_without_any_real_acquisition(monkeypatch):
    calls=[]
    class Client:
        calls=0;log=[]
        def get(self,endpoint):
            calls.append(endpoint)
            if '/commits/' in endpoint:return SimpleNamespace(body={'sha':'a'*40})
            return SimpleNamespace(body={'private':False,'id':1,'default_branch':'main'})
    monkeypatch.setattr(collect,'list_closed',lambda *a:{'items':[]})
    monkeypatch.setattr(collect,'select_pairs',lambda *a:{'selected':list(range(20)),'stop_reason':'cap'})
    result=collect.collect_metadata(Client(),{'repositories':['one/repo','two/repo'],'terminal_lower':'2022-01-01T00:00:00Z','maximum_pairs':40})
    assert result['selected_pairs']==40 and result['complete']
    assert calls==['repos/one/repo','repos/one/repo/commits/main','repos/two/repo','repos/two/repo/commits/main']


def test_acquisition_ceiling_marks_other_repositories_unattempted():
    class Client:
        calls=0;log=[]
        def get(self,endpoint):raise Ceiling('synthetic ceiling')
    result=collect.collect_metadata(Client(),{'repositories':['one/repo','two/repo']})
    assert not result['complete'] and result['selected_pairs']==0
    assert result['repositories'][1]['status']=='unattempted'


def test_repository_ceiling_continues_next_allocation(monkeypatch):
    from benchmarks.s17b.selection import RepositoryCeiling
    calls=[]
    class Client:
        calls=0;log=[]
        def get(self,endpoint):
            calls.append(endpoint)
            if endpoint=='repos/one/repo':raise RepositoryCeiling('repository ceiling')
            if '/commits/' in endpoint:return SimpleNamespace(body={'sha':'a'*40})
            return SimpleNamespace(body={'private':False,'id':1,'default_branch':'main'})
    monkeypatch.setattr(collect,'list_closed',lambda *a:{'items':[]})
    monkeypatch.setattr(collect,'select_pairs',lambda *a:{'selected':[],'stop_reason':'order-exhausted'})
    answer=collect.collect_metadata(Client(),{'repositories':['one/repo','two/repo'],'terminal_lower':'2022-01-01T00:00:00Z','maximum_pairs':40})
    assert not answer['complete']
    assert answer['repositories'][1]['status']=='metadata-only'
    assert calls[-1]=='repos/two/repo/commits/main'
