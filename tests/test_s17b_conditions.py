"""Vega C1-C3/M1 and minor regressions, with no API or real fetch."""
from copy import deepcopy
from types import SimpleNamespace
import json

import pytest

from benchmarks.s17b import acquire,selection,graph,checkpoint
from .test_s17b_selection import pr,POLICY
from .test_s17b_acquire import Client,Page,link


@pytest.mark.parametrize('skew,accepted',[(1,True),(-60,True),(60,True),(61,False)])
def test_c1_terminal_event_tolerance(skew,accepted):
    from datetime import timedelta
    value=pr(1,merged_at='2025-04-01T00:00:00Z')
    value['_timeline'][0]['created_at']=(selection.timestamp(value['merged_at'])+timedelta(seconds=skew)).isoformat()
    assert (selection.timeline_filter(value) is None)==accepted


@pytest.mark.parametrize('last_offset,accepted',[(1,True),(60,True),(61,False)])
def test_c1_last_terminal_event_required(last_offset,accepted):
    from datetime import timedelta
    value=pr(1,merged_at='2025-04-01T00:00:00Z')
    value['_timeline'].append({'event':'closed','created_at':(selection.timestamp(value['merged_at'])+timedelta(seconds=last_offset)).isoformat()})
    proof=selection.terminal_proof(value)
    assert (proof['reason'] is None)==accepted
    assert proof['last_terminal_skew_seconds']==last_offset


@pytest.mark.parametrize('endpoint',['repos/some-other/unlisted-repo','repos/../user','repos/example/repo/../user',
 'repos/example/repo//pulls','repos/example/repo/pulls/%2e%2e','repos/example/repo/pulls/..','rate_limit'])
def test_c2_allowlist_precedes_any_runner(tmp_path,endpoint):
    class Permit:
        def verify(self):return {'repositories':['example/repo'],'gh_version':'test','api_version':'test','maximum_get_requests':1500}
    calls=[]
    client=acquire.GhGet(Permit(),tmp_path,lambda *a,**k:calls.append(a),version_reader=lambda:'test')
    with pytest.raises(ValueError):client.get(endpoint)
    assert calls==[] and not list(tmp_path.iterdir())


def test_m1_provably_out_of_window_never_requests_details():
    values=[pr(1),pr(2),pr(3,created_at='2020-01-01T00:00:00Z',closed_at='2021-01-01T00:00:00Z'),pr(4,closed_at=POLICY['collection_cutoff'])]
    requested=[]
    def load(n):requested.append(n);return next(p for p in values if p['number']==n)
    result=selection.select_pairs(values,1,'main',POLICY,load)
    assert set(requested)=={1,2}
    assert result['list_counts']['terminal_window_exclusions']==[3,4]


def test_m5_moved_list_record_keeps_highest_update_and_logs_move():
    prefix='repos/example/repo/pulls'
    old=pr(1,updated_at='2025-04-02T00:00:00Z',title='old')
    new={**old,'updated_at':'2025-04-03T00:00:00Z','title':'new'}
    client=Client({prefix:Page([old],link(prefix+'?page=2')),prefix+'?page=2':Page([new])})
    result=acquire.list_closed(client,'example/repo',POLICY['terminal_lower'])
    assert result['items']==[new] and len(result['duplicates'])==1


def test_m5_contradictory_terminal_data_still_fails():
    prefix='repos/example/repo/pulls';old=pr(1,updated_at='2025-04-02T00:00:00Z')
    new={**old,'updated_at':'2025-04-03T00:00:00Z','closed_at':'2025-04-02T00:00:00Z'}
    client=Client({prefix:Page([old],link(prefix+'?page=2')),prefix+'?page=2':Page([new])})
    with pytest.raises(selection.Incomplete,match='terminal'):acquire.list_closed(client,'example/repo',POLICY['terminal_lower'])


def test_c1_health_stop_first_ten_complete_merged_timelines_only():
    class Synthetic:
        def __init__(self):self.calls=[]
        def get(self,endpoint,**kw):
            self.calls.append(endpoint)
            n=int(endpoint.split('/')[4]);value=pr(n,merged_at='2025-04-01T00:00:00Z')
            if '/timeline' in endpoint:return Page([])
            if '/files' in endpoint:pytest.fail('R2: failed timeline must not load files')
            return Page(value)
    client=Synthetic();metadata=acquire.Metadata(client,'example/repo',POLICY,'main')
    for n in range(1,10):assert metadata.load(n)['_terminal_event_proof']['reason']=='lifecycle-terminal-unproven'
    metadata.load(1) # Cached PR is not a second health observation.
    with pytest.raises(selection.RepositoryIncomplete,match='health stop'):metadata.load(10)
    with pytest.raises(selection.RepositoryIncomplete):metadata.load(11)
    assert len(client.calls)==20 and len(metadata.terminal_health)==10


def test_c1_skew_is_recorded_next_to_metadata():
    prefix='repos/example/repo/pulls/1';value=pr(1,merged_at='2025-04-01T00:00:00Z')
    timeline=[{'event':'merged','created_at':'2025-04-01T00:00:15Z'}]
    metadata=acquire.Metadata(Client({prefix:Page(value),'repos/example/repo/issues/1/timeline':Page(timeline),prefix+'/files':Page([{'filename':'use.py'}])}),'example/repo',POLICY,'main')
    result=metadata.load(1)
    assert result['_terminal_event_proof']['skew_seconds']==15
    assert metadata.ledger[1]['terminal_event_proof']==result['_terminal_event_proof']


class ClonePermit:
    def verify(self):return {'repositories':['example/repo'],'maximum_git_bytes':20}


def clone_runner(calls):
    def run(args,**kw):
        calls.append(args)
        if args[1:3]==['rev-parse','--verify']:stdout=b'a'*40+b'\n'
        else:stdout=b''
        return SimpleNamespace(returncode=0,stdout=stdout,stderr=b'')
    return run


def test_c3_clone_and_default_fetch_are_gated_metered_and_pinned(tmp_path):
    calls=[];fetches=[];permit=ClonePermit();budget=acquire.GitBudget.from_policy(permit)
    def transport(args,**kw):fetches.append((args,kw));return acquire.FetchReceipt('a'*40,8)
    g,record=acquire.prepare_clone(tmp_path/'clone','example/repo','main','a'*40,permit,budget,transport,clone_runner(calls))
    assert fetches[0][0]==['git','fetch','--no-tags','origin','refs/heads/main']
    assert record['fetched_default_sha']==record['expected_default_sha']=='a'*40 and budget.used==8
    assert ['git','remote','add','origin','https://github.com/example/repo.git'] in calls
    acquire.fetch_head(g,7,'a'*40,permit,budget,lambda *a,**kw:acquire.FetchReceipt('a'*40,10))
    assert budget.used==18
    with pytest.raises(selection.Ceiling):acquire.fetch_head(g,8,'a'*40,permit,budget,lambda *a,**kw:acquire.FetchReceipt('a'*40,3))
    assert budget.used==21 and budget.stopped


def test_c3_no_permission_means_no_clone_or_runner(tmp_path):
    class Deny:
        def verify(self):raise PermissionError('not authorized')
    with pytest.raises(PermissionError):acquire.prepare_clone(tmp_path/'clone','example/repo','main','a'*40,Deny(),acquire.GitBudget(),runner=lambda *a,**k:pytest.fail('No runner'))
    assert not (tmp_path/'clone').exists()


def test_c3_moving_default_is_not_silently_replaced(tmp_path):
    budget=acquire.GitBudget(20)
    with pytest.raises(selection.Incomplete,match='default SHA'):
        acquire.prepare_clone(tmp_path/'clone','example/repo','main','b'*40,ClonePermit(),budget,lambda *a,**kw:acquire.FetchReceipt('a'*40,8),clone_runner([]))
    assert budget.used==8


def test_m4_reused_head_has_no_second_fetch_or_byte_charge():
    permit=ClonePermit();budget=acquire.GitBudget(20);calls=[]
    g=SimpleNamespace(repo='synthetic',commit=lambda c:c,bind=lambda *a:None)
    def transport(*a,**kw):calls.append(1);return acquire.FetchReceipt('a'*40,8)
    for _ in range(2):assert acquire.fetch_head(g,1,'a'*40,permit,budget,transport)=='a'*40
    assert calls==[1] and budget.used==8


def test_m7_git_operational_failure_is_not_textual_conflict():
    g=SimpleNamespace(commit=lambda c:c,git=lambda *a,**kw:SimpleNamespace(returncode=128))
    with pytest.raises(graph.Unresolved,match='operational'):graph.native_merge(g,'a','b')


def test_m6_template_status_cannot_form_checkpoint(tmp_path):
    policy=json.loads((checkpoint.ROOT/'benchmarks/s17b/policy.json').read_text())
    policy.update(POLICY,api_version='test',gh_version='test',detector_commit='a'*40)
    policy.update(checkpoint.runtime_pins())
    with pytest.raises(ValueError,match='ready status'):checkpoint.prepare(policy,tmp_path/'checkpoint')
    assert not (tmp_path/'checkpoint').exists()


def test_c3_unmeasurable_initial_transfer_stops_before_any_next_clone(tmp_path):
    budget=acquire.GitBudget(20);permit=ClonePermit()
    with pytest.raises(selection.Ceiling,match='Unmeasurable'):
        acquire.prepare_clone(tmp_path/'first','example/repo','main','a'*40,permit,budget,lambda *a,**kw:acquire.FetchReceipt(None,None),clone_runner([]))
    with pytest.raises(selection.Ceiling):
        acquire.prepare_clone(tmp_path/'second','example/repo','main','a'*40,permit,budget,runner=lambda *a,**kw:pytest.fail('No next clone runner'))
    assert budget.stopped and not (tmp_path/'second').exists()


def test_m4_failed_head_is_not_retried_on_reused_pair():
    calls=[];budget=acquire.GitBudget(20);permit=ClonePermit()
    g=SimpleNamespace(repo='synthetic',commit=lambda c:c)
    def transport(*a,**kw):calls.append(1);return acquire.FetchReceipt(None,4,'unavailable')
    for _ in range(2):
        with pytest.raises(selection.Incomplete,match='unavailable'):acquire.fetch_head(g,1,'a'*40,permit,budget,transport)
    assert calls==[1] and budget.used==4


@pytest.mark.parametrize('offset,accepted',[(1,True),(2,False)])
def test_e1_terminal_proof_uses_policy_tolerance(offset,accepted):
    from datetime import timedelta
    value=pr(1,merged_at='2025-04-01T00:00:00Z')
    value['_timeline'].append({'event':'closed','created_at':(selection.timestamp(value['merged_at'])+timedelta(seconds=offset)).isoformat()})
    proof=selection.terminal_proof(value,{'terminal_event_tolerance_seconds':1})
    assert (proof['reason'] is None)==accepted and proof['tolerance_seconds']==1


def test_e2_natural_permit_clone_call_passes_budget_by_keyword(tmp_path,monkeypatch):
    permit=checkpoint.Permit(tmp_path/'unwritten-checkpoint',tmp_path/'unwritten-authorization')
    monkeypatch.setattr(checkpoint.Permit,'verify',ClonePermit.verify)
    budget=acquire.GitBudget.from_policy(permit);calls=[]
    g,record=permit.prepare_clone(tmp_path/'clone','example/repo','main','a'*40,budget,
        transport=lambda *a,**kw:acquire.FetchReceipt('a'*40,8),runner=clone_runner(calls))
    assert record['fetched_default_sha']=='a'*40 and budget.used==8
    assert ['git','remote','add','origin','https://github.com/example/repo.git'] in calls
    assert not permit.checkpoint.exists() and not permit.authorization.exists()
