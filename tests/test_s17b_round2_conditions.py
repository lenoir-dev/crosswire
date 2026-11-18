"""R2-C1/C2 and minor fixes; only fake requests and synthetic Git graphs."""
from copy import deepcopy
import hashlib,json
from pathlib import Path
from types import SimpleNamespace

import pytest

from benchmarks.s17b import acquire,collect,entry,graph,pipeline,checkpoint
from benchmarks.s17b.selection import Incomplete,Ceiling,RepositoryIncomplete,metadata_filter
from .test_s17b_selection import pr
from .test_s17b_round2 import policy,response


class Permit:
    def verify(self):return policy()


def client_at(tmp_path,runner):
    return acquire.GhGet(Permit(),tmp_path,runner,version_reader=lambda:'synthetic gh',wait=lambda n:None,clock=lambda:1000)


@pytest.mark.parametrize('stage',['detail','timeline','files'])
def test_pr_scoped_failure_is_cached_stub_with_http_exit_status(tmp_path,stage):
    calls=[]
    def runner(args,**kw):
        calls.append(args[-1]);path=args[-1].split('?',1)[0]
        broken=(stage=='detail' and path.endswith('/pulls/59') or stage=='timeline' and '/timeline' in path or stage=='files' and '/files' in path)
        if broken:return response(404,stderr='not available')
        if '/timeline' in path:return response(body=pr(59)['_timeline'])
        return response(body=pr(59))
    client=client_at(tmp_path,runner);metadata=acquire.Metadata(client,'example/repo',policy(),'main')
    stub=metadata.load(59)
    assert stub['_metadata_status']=='metadata-unavailable'
    assert metadata_filter(stub,'main',policy())=='invalid-metadata'
    assert 'created_at' not in stub and 'closed_at' not in stub
    failure=stub['_metadata_unavailable']
    assert failure['stage']==stage and failure['http_status']==404 and failure['exit_status']==1
    count=len(calls);assert metadata.load(59)==stub and len(calls)==count


def test_commit_failure_consumes_selected_pair_slot_and_is_not_retried(tmp_path,monkeypatch):
    calls=[]
    client=client_at(tmp_path,lambda args,**kw:(calls.append(args[-1]) or response(404)))
    metadata=acquire.Metadata(client,'example/repo',policy(),'main')
    monkeypatch.setattr(pipeline,'fetch_head',lambda graph,n,expected,*a:expected)
    slot={'A':59,'B':60,'slot':3,'rank':9,'hash':'a'*64,'details':{
        'A':{'head':{'sha':'a'*40},'commits':1},'B':{'head':{'sha':'b'*40},'commits':1}}}
    for _ in range(2):
        result=pipeline.prepare_pair(slot,None,'d'*40,metadata,Permit(),None,None)
        assert result['slot']==3 and result['status']=='unlabelled' and result['pr_failure']['stage']=='commits'
    assert len(calls)==1


def test_five_distinct_failed_prs_stop_only_repository(tmp_path):
    calls=[];client=client_at(tmp_path,lambda args,**kw:(calls.append(args[-1]) or response(404)))
    metadata=acquire.Metadata(client,'example/repo',policy(),'main')
    for n in range(1,5):assert metadata.load(n)['_metadata_status']=='metadata-unavailable'
    metadata.load(1)
    with pytest.raises(RepositoryIncomplete,match='PR failure health'):metadata.load(5)
    with pytest.raises(RepositoryIncomplete):metadata.load(6)
    assert len(calls)==5 and not client.stopped


@pytest.mark.parametrize('endpoint,timeout',[
 ('repos/example/repo/pulls/59',120),('repos/example/repo/issues/59/timeline',120),
 ('repos/example/repo/pulls/59/files',120),('repos/example/repo/pulls/59/commits',120),
 ('repos/example/repo/pulls',60),('repos/example/repo/commits/main',60)])
def test_pr_scoped_timeout_120_keeps_other_requests_60(tmp_path,endpoint,timeout):
    seen=[];client=client_at(tmp_path,lambda *a,**kw:(seen.append(kw['timeout']) or response()))
    client.get(endpoint);assert seen==[timeout]


def test_total_wait_cap_900_is_global_and_persisted(tmp_path):
    count=[];waits=[]
    client=acquire.GhGet(Permit(),tmp_path,lambda *a,**kw:(count.append(1) or response(429,{'Retry-After':'300'})),version_reader=lambda:'synthetic gh',wait=waits.append,clock=lambda:1000)
    with pytest.raises(Incomplete):client.get('repos/example/repo/pulls/1')
    assert sum(waits)==client.total_wait_seconds==client.wait_budget_used==900
    with pytest.raises(Ceiling,match='rate-limited'):client.get('repos/example/repo/pulls/2')
    assert len(count)==4 and sum(waits)==900 and client.stopped
    restarted=client_at(tmp_path,lambda *a,**kw:pytest.fail('No request after total wait stop'))
    with pytest.raises(Ceiling):restarted.get('repos/other/repo/pulls')
    assert restarted.wait_budget_used==900
    assert json.loads((tmp_path/'cohort-stop.json').read_text())['reason']=='total-wait-ceiling'


def test_interrupted_reserved_wait_still_counts_on_restart(tmp_path):
    def killed(seconds):raise KeyboardInterrupt()
    client=acquire.GhGet(Permit(),tmp_path,lambda *a,**kw:response(429,{'Retry-After':'300'}),version_reader=lambda:'synthetic gh',wait=killed,clock=lambda:1000)
    with pytest.raises(KeyboardInterrupt):client.get('repos/example/repo/pulls/1')
    restored=client_at(tmp_path,lambda *a,**kw:response())
    restored.get('repos/other/repo/pulls')
    assert restored.wait_budget_used==300 and restored.total_wait_seconds==300
    assert restored.wait_events[0]['status']=='complete' and restored.wait_events[0]['resumed']


def test_pre_update_search_does_not_walk_old_default_history(monkeypatch):
    seen=[]
    def ancestor(a,b):
        seen.append((a,b))
        if a=='C':return b in {'head','merge','default'}
        return False
    fake=SimpleNamespace(chain=lambda head:['head','merge','candidate',*['old-'+str(i) for i in range(1000)]] if head=='head' else ['default'],
        ancestor=ancestor,parents=lambda c:{'head':['merge'],'merge':['candidate','default']}[c])
    monkeypatch.setattr(graph,'own_bases',lambda *a:{'A':'base','B':'base','L':'base'})
    monkeypatch.setattr(graph,'contamination',lambda *a:{'reason':None,'test':'all-three-pass'})
    result=graph.pre_update_head(fake,'earlier','head','base','C','A','default',['candidate','merge','head'])
    assert result['candidate']=='candidate' and len(seen)<15
    assert not any(b.startswith('old-') for _,b in seen)


@pytest.mark.parametrize('failure',['404','timeouts'])
def test_round1_failing_timeline_shape_end_to_end_continues_same_walk(tmp_path,monkeypatch,failure):
    from .test_s17b_entry import adapters
    root=tmp_path/'round';base_runner,_,_,_,_=adapters(monkeypatch,root)
    configured=policy();configured.update(repositories=['one/repo','two/repo'],maximum_git_bytes=100,maximum_pairs=40,gh_version='gh version synthetic')
    monkeypatch.setattr(checkpoint.Permit,'verify',lambda self:deepcopy(configured))
    requests=[];timeouts=[];waits=[]
    def head(n):return hashlib.sha1(str(n).encode()).hexdigest()
    def runner(args,**kw):
        if args[:2]!=['gh','api']:return base_runner(args,**kw)
        requests.append(args[-1]);parts=args[-1].split('?',1)[0].split('/');first=parts[1]=='one'
        if len(parts)==3:return response(body={'private':False,'id':2,'default_branch':'main'})
        if parts[3]=='commits':return response(body={'sha':'a'*40})
        if len(parts)==4:return response(body=[pr(n) for n in ((56,59,73,78) if first else (1,2))])
        n=int(parts[4]);value=pr(n);value['base']['repo']['id']=2
        if parts[3]=='issues':
            if first and n==59:
                timeouts.append(kw['timeout'])
                if failure=='404':return response(404,stderr='synthetic PR timeline unavailable')
                import subprocess
                raise subprocess.TimeoutExpired('fake timeline',kw['timeout'],stderr=b'fake slow PR timeline')
            return response(body=value['_timeline'])
        if len(parts)==5:return response(body={**value,'head':{'sha':head(n)},'commits':1})
        if parts[5]=='files':return response(body=value['_files'])
        if parts[5]=='commits':return response(body=[{'sha':head(n)}])
        raise AssertionError(parts)
    def transport(args,**kwargs):
        assert (root/'metadata.json').exists()
        return acquire.FetchReceipt('a'*40 if args[-1].startswith('refs/heads/') else head(int(args[-1].split('/')[2])),1)
    real=entry.GhGet
    monkeypatch.setattr(entry,'GhGet',lambda *a,**kw:real(*a,**kw,wait=waits.append,clock=lambda:1000))
    result=entry.acquire(checkpoint.Permit(tmp_path/'absent',tmp_path/'absent'),root,runner=runner,transport=transport)
    metadata=json.loads((root/'metadata.json').read_text())
    selection=metadata['repositories'][0]['selection']
    assert selection['stop_reason']=='order-exhausted' and len(selection['ledger'])==6
    assert [(s['A'],s['B']) for s in selection['selected']]==[(73,78),(56,78),(56,73)]
    failed=[v for v in selection['ledger'] if 59 in (v['A'],v['B'])]
    assert len(failed)==3 and all(v['outcome']=='invalid-metadata' and 'slot' not in v for v in failed)
    assert len(timeouts)==(1 if failure=='404' else 3) and set(timeouts)=={120}
    assert result['status']=='acquired' and result['apparatus_report']['one/repo']['pr_scoped_failures']==1
    assert result['apparatus_report']['one/repo']['retries']==(0 if failure=='404' else 2)
    assert result['apparatus_report']['one/repo']['wait_completed_seconds']==(0 if failure=='404' else 3)
    assert result['repositories'][1]['status']=='graph-acquired' and len(result['repositories'][0]['slots'])==3
    assert all(s['status']=='ready' for r in result['repositories'] for s in r['slots'])
    assert not (tmp_path/'absent').exists()


def test_unknown_stderr_is_preserved_and_not_retried(tmp_path):
    calls=[];client=client_at(tmp_path,lambda *a,**kw:(calls.append(1) or SimpleNamespace(returncode=1,stdout='',stderr='unrecognized transport diagnostic')))
    with pytest.raises(Incomplete):client.get('repos/example/repo/pulls')
    assert len(calls)==1
    value=json.loads((tmp_path/'000001.result.json').read_text())
    assert value['exit_status']==1 and value['http_status'] is None and value['stderr']=='unrecognized transport diagnostic'


def test_request_and_rate_ceilings_are_never_pr_stubs(tmp_path):
    from benchmarks.s17b.http import RateLimited
    client=client_at(tmp_path/'rate',lambda *a,**kw:response(429,{'Retry-After':'301'}))
    metadata=acquire.Metadata(client,'example/repo',policy(),'main')
    with pytest.raises(RateLimited):metadata.load(59)
    assert metadata.failures=={} and 59 not in metadata.cache
    configured=policy();configured['per_repository_metadata_get_budget']=0
    limited=SimpleNamespace(verify=lambda:configured)
    client=acquire.GhGet(limited,tmp_path/'budget',lambda *a,**kw:pytest.fail('No GET at ceiling'),version_reader=lambda:'synthetic gh')
    metadata=acquire.Metadata(client,'example/repo',configured,'main')
    with pytest.raises(Ceiling):metadata.load(59)
    assert metadata.failures=={}


def test_pr_failure_cache_and_health_are_shared_between_metadata_and_graph_phases(tmp_path):
    calls=[];client=client_at(tmp_path,lambda args,**kw:(calls.append(args[-1]) or response(404)))
    first=acquire.Metadata(client,'example/repo',policy(),'main')
    for n in range(1,5):first.load(n)
    next_phase=acquire.Metadata(client,'example/repo',policy(),'main')
    assert next_phase.load(1)['_metadata_status']=='metadata-unavailable' and len(calls)==4
    from benchmarks.s17b.http import PRMetadataUnavailable
    with pytest.raises(PRMetadataUnavailable):next_phase.commits(5,1)
    assert next_phase.pr_failure_health_stopped and len(next_phase.failures)==5
    with pytest.raises(RepositoryIncomplete):next_phase.commits(6,1)
    assert len(calls)==5


def test_health_stopped_selected_tail_has_no_further_head_fetch(monkeypatch):
    from benchmarks.s17b.acquire import GitBudget
    metadata=SimpleNamespace(pr_failure_health_stopped=True)
    monkeypatch.setattr(pipeline,'fetch_head',lambda *a:pytest.fail('No head request after repository health stop'))
    slot={'A':1,'B':2,'slot':7,'rank':12,'hash':'b'*64}
    result=pipeline.prepare_slots([slot],None,None,metadata,Permit(),GitBudget(),None)
    assert result[0]['slot']==7 and result[0]['status']=='unattempted' and result[0]['reason']=='repository-pr-failure-health-stop'


def test_five_failed_prs_in_collector_do_not_stop_other_repository(tmp_path):
    def runner(args,**kw):
        parts=args[-1].split('?',1)[0].split('/')
        if len(parts)==3:return response(body={'private':False,'id':1,'default_branch':'main'})
        if parts[3]=='commits':return response(body={'sha':'a'*40})
        if len(parts)==4:return response(body=[pr(n) for n in range(1,7)] if parts[1]=='example' else [])
        return response(404)
    client=client_at(tmp_path,runner)
    result=collect.collect_metadata(client,policy())
    assert len(result['repositories'][0]['pr_failures'])==5
    assert result['repositories'][0]['status']=='acquisition-incomplete'
    assert result['repositories'][1]['status']=='metadata-only' and not result['complete']


def test_per_repository_report_counts_failures_retries_waits_and_rescue_outcomes():
    from benchmarks.s17b.reporting import repository_report
    endpoint='repos/example/repo/pulls/59'
    client=SimpleNamespace(log=[{'request':1,'endpoint':endpoint,'operation_attempt':1,'http_status':503},
        {'request':2,'endpoint':endpoint,'operation_attempt':2,'http_status':429,'headers':{'retry-after':'5'}},
        {'request':3,'endpoint':endpoint,'operation_attempt':3,'http_status':200}],
        pr_failures={'example/repo':{60:[{'stage':'commits','http_status':404,'exit_status':1}]}},
        wait_events=[{'endpoint':endpoint,'planned_seconds':1,'waited_seconds':1,'status':'complete'},
                     {'endpoint':endpoint,'planned_seconds':5,'waited_seconds':5,'status':'complete'}])
    slots=[{'head_kind':'pre-update','head_adjustment':{}},
           {'head_kind':'final-head','pre_update_rejection':'pre-update-contaminated-heads:patch-intersection'}]
    report=repository_report(client,'example/repo',slots)
    assert report['pr_scoped_failures']==1 and report['retries_by_cause']=={'http-5xx':1,'rate-limit':1}
    assert report['wait_completed_seconds']==report['wait_reserved_seconds']==6
    assert report['pre_update_rescues']['attempted']==2 and report['pre_update_rescues']['accepted']==report['pre_update_rescues']['rejected']==1
