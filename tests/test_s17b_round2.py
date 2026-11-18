"""P6 apparatus regressions: fake GETs and local synthetic graphs only."""
from copy import deepcopy
from types import SimpleNamespace
import json
from pathlib import Path
import subprocess

import pytest

from benchmarks.s17b.acquire import GhGet
from benchmarks.s17b import collect,graph,pipeline
from benchmarks.s17b.selection import Incomplete,Ceiling
from .test_s17b_graph import independent


def policy():
    value=json.loads((Path(__file__).parents[1]/'benchmarks/s17b/policy.json').read_text())
    value.update(repositories=['example/repo','other/repo'],gh_version='synthetic gh')
    return value


class Permit:
    def verify(self):return policy()


def response(status=200,headers=None,body=None,stderr='',exit=None):
    text=f'HTTP/2.0 {status} status\n'+''.join(f'{k}: {v}\n' for k,v in (headers or {}).items())+'\n'+json.dumps([] if body is None else body)
    return SimpleNamespace(returncode=(0 if status==200 else 1) if exit is None else exit,stdout=text,stderr=stderr)


def fake_client(tmp_path,events):
    calls=[];waits=[];events=iter(events)
    def runner(args,**kw):
        calls.append(args)
        value=next(events)
        if isinstance(value,Exception):raise value
        return value
    client=GhGet(Permit(),tmp_path,runner,version_reader=lambda:'synthetic gh',wait=waits.append,clock=lambda:1000)
    return client,calls,waits


def test_r2a_round1_timeline_failure_recovered_only_by_transport_retry(tmp_path):
    client,calls,waits=fake_client(tmp_path,[response(502,stderr='gateway unavailable'),response()])
    assert client.get('repos/example/repo/issues/59/timeline',per_page=100).body==[]
    assert len(calls)==client.calls==2 and waits==[1]
    results=[json.loads(p.read_text()) for p in sorted(tmp_path.glob('*.result.json'))]
    assert [(v['exit_status'],v['http_status']) for v in results]==[(1,502),(0,200)]
    assert results[0]['stderr']=='gateway unavailable'


@pytest.mark.parametrize('status,headers,wait',[ (429,{'Retry-After':'5'},5),(403,{'Retry-After':'2'},2),(403,{'x-ratelimit-remaining':'0','x-ratelimit-reset':'1010'},10)])
def test_rate_limit_exceptions_honor_wait_then_retry(tmp_path,status,headers,wait):
    client,calls,waits=fake_client(tmp_path,[response(status,headers),response()])
    client.get('repos/example/repo/pulls')
    assert len(calls)==2 and waits==[wait]


@pytest.mark.parametrize('status',[400,401,403,404,410,422])
def test_other_4xx_never_retries(tmp_path,status):
    client,calls,waits=fake_client(tmp_path,[response(status)])
    with pytest.raises(Incomplete):client.get('repos/example/repo/pulls')
    assert len(calls)==1 and waits==[]


@pytest.mark.parametrize('status,headers',[(429,{'Retry-After':'301'}),(403,{'x-ratelimit-remaining':'0','x-ratelimit-reset':'1301'}),(429,{})])
def test_rate_wait_over_300_or_unknown_stops_globally(tmp_path,status,headers):
    client,calls,waits=fake_client(tmp_path,[response(status,headers)])
    with pytest.raises(Ceiling,match='acquisition-incomplete-rate-limited'):client.get('repos/example/repo/pulls')
    with pytest.raises(Ceiling):client.get('repos/other/repo/pulls')
    assert len(calls)==1 and waits==[] and client.stopped


def test_r2b_repository_failure_continues_other_repository(monkeypatch):
    calls=[]
    class Client:
        calls=0;log=[]
        def get(self,endpoint):
            calls.append(endpoint)
            if endpoint=='repos/example/repo':raise Incomplete('synthetic failure')
            if '/commits/' in endpoint:return SimpleNamespace(body={'sha':'a'*40})
            return SimpleNamespace(body={'private':False,'id':1,'default_branch':'main'})
    monkeypatch.setattr(collect,'list_closed',lambda *a:{'items':[]})
    result=collect.collect_metadata(Client(),policy())
    assert result['repositories'][0]['status']=='acquisition-incomplete'
    assert result['repositories'][1]['status']=='metadata-only' and not result['complete']


def test_r2c_iniconfig_like_merge_from_default_selects_pre_update_head(repo):
    g,D,A,B,C=independent(repo)
    repo.checkout('B');repo.git('merge','--no-ff','--no-edit','main');updated=g.text('rev-parse','HEAD')
    repo.write('after.txt','later work');final=repo.commit('after default update')
    proof=graph.pre_update_head(g,A,final,D,C,'A',C,[B,updated,final])
    assert proof['heads']=={'A':A,'B':B} and proof['candidate']==B
    assert proof['contamination']['test']=='all-three-pass'


def test_round2_policy_changes_only_round_and_apparatus_fields():
    directory=Path(__file__).parents[1]/'benchmarks/s17b'
    first=json.loads((directory/'policy-round1.json').read_text());second=json.loads((directory/'policy.json').read_text())
    stripped={k:v for k,v in second.items() if k not in {'round_id','apparatus'}}
    assert stripped==first
    assert (json.dumps(stripped,sort_keys=True,indent=2)+'\n').encode()==(directory/'policy-round1.json').read_bytes()
    import hashlib
    assert hashlib.sha256((directory/'selection.py').read_bytes()).hexdigest()==second['apparatus']['selection_source_sha256']


@pytest.mark.parametrize('failure',[
    subprocess.TimeoutExpired('synthetic gh',60,stderr=b'timed out'),
    ConnectionResetError('connection reset'),response(exit=1,stderr='error connecting to api.github.com: connection reset by peer')])
def test_timeout_and_connection_failures_retry_with_result_records(tmp_path,failure):
    client,calls,waits=fake_client(tmp_path,[failure,response()])
    client.get('repos/example/repo/issues/59/timeline')
    assert len(calls)==2 and waits==[1]
    data=json.loads(sorted(tmp_path.glob('*.result.json'))[0].read_text())
    assert data['status']=='failed' and 'stderr' in data and 'exit_status' in data


def test_three_attempt_limit_backoff_and_restart_never_retries_again(tmp_path):
    client,calls,waits=fake_client(tmp_path,[response(503)]*3)
    with pytest.raises(Incomplete):client.get('repos/example/repo/pulls')
    assert client.calls==len(calls)==3 and waits==[1,2]
    restarted=GhGet(Permit(),tmp_path,lambda *a,**kw:pytest.fail('No fourth attempt'),version_reader=lambda:'synthetic gh')
    with pytest.raises(Incomplete,match='Prior GET'):restarted.get('repos/example/repo/pulls')
    assert restarted.calls==3 and len(list(tmp_path.glob('*.result.json')))==3


def test_retry_counts_against_metadata_sub_budget_without_using_reserve(tmp_path):
    configured=policy();configured['per_repository_metadata_get_budget']=1
    class Limited:
        def verify(self):return configured
    calls=[];client=GhGet(Limited(),tmp_path,lambda *a,**kw:(calls.append(a) or response(502)),version_reader=lambda:'synthetic gh',wait=lambda n:None)
    from benchmarks.s17b.selection import RepositoryCeiling
    with pytest.raises(RepositoryCeiling):client.get('repos/example/repo/pulls')
    assert client.calls==len(calls)==1
    client.runner=lambda *a,**kw:(calls.append(a) or response())
    client.get('repos/example/repo/pulls/1/commits')
    assert client.calls==len(calls)==2


def test_retry_counts_against_global_ceiling(tmp_path):
    configured=policy();configured['maximum_get_requests']=1
    class Limited:
        def verify(self):return configured
    calls=[];client=GhGet(Limited(),tmp_path,lambda *a,**kw:(calls.append(a) or response(502)),version_reader=lambda:'synthetic gh',wait=lambda n:None)
    with pytest.raises(Ceiling):client.get('repos/example/repo/pulls')
    assert client.calls==len(calls)==1


def test_rate_wait_300_is_allowed_and_restored_rate_stop_is_global(tmp_path):
    client,calls,waits=fake_client(tmp_path/'allowed',[response(429,{'Retry-After':'300'}),response()])
    client.get('repos/example/repo/pulls')
    assert len(calls)==2 and sum(waits)==300
    blocked,_,_=fake_client(tmp_path/'blocked',[response(429,{'Retry-After':'301'})])
    with pytest.raises(Ceiling):blocked.get('repos/example/repo/pulls')
    restarted=GhGet(Permit(),tmp_path/'blocked',lambda *a,**kw:pytest.fail('Must preserve global rate stop'),version_reader=lambda:'synthetic gh')
    with pytest.raises(Ceiling,match='rate-limited'):restarted.get('repos/other/repo/pulls')


def test_attempt_stderr_redacts_tokens_headers_url_credentials_and_local_home(tmp_path,monkeypatch):
    monkeypatch.setenv('GH_TOKEN','secret_from_environment')
    stderr='Authorization: Bearer dangerous\nsecret_from_environment ghp_abcdef github_pat_qwerty https://user:password@github.com '+str(Path.home())+'/private.txt'
    client,calls,_=fake_client(tmp_path,[response(404,stderr=stderr)])
    with pytest.raises(Incomplete):client.get('repos/example/repo/pulls')
    result=json.loads(sorted(tmp_path.glob('*.result.json'))[0].read_text())
    assert result['exit_status']==1 and result['http_status']==404
    assert all(token not in result['stderr'] for token in ('dangerous','secret_from_environment','ghp_abcdef','github_pat_qwerty','password',str(Path.home())))


@pytest.mark.parametrize('earlier',['A','B'])
def test_r2c_pipeline_records_final_and_pre_update_heads_separately(repo,monkeypatch,earlier):
    g,D,E,F,C=independent(repo)
    repo.checkout('B');repo.git('merge','--no-ff','--no-edit','main');merged=g.text('rev-parse','HEAD')
    repo.write('after.txt','later work');final=repo.commit('after update')
    other='B' if earlier=='A' else 'A';heads={earlier:E,other:final}
    details={earlier:{'state':'closed','created_at':'2024-01-01T00:00:00Z','closed_at':'2025-02-01T00:00:00Z','merged_at':'2025-02-01T00:00:00Z','merge_commit_sha':C,'head':{'sha':E},'commits':1},
             other:{'state':'closed','created_at':'2024-01-01T00:00:00Z','closed_at':'2025-03-01T00:00:00Z','head':{'sha':final},'commits':3}}
    slot={'A':1,'B':2,'slot':1,'rank':1,'hash':'a'*64,'details':details}
    monkeypatch.setattr(pipeline,'fetch_head',lambda graph,n,expected,*a:expected)
    lists={slot[earlier]:[E],slot[other]:[F,merged,final]}
    metadata=SimpleNamespace(commits=lambda n,count:(lists[n],[]))
    result=pipeline.prepare_pair(slot,g,C,metadata,Permit(),None,None)
    assert result['status']=='ready' and result['head_kind']=='pre-update'
    assert result['heads'][other]==F and result['final_heads'][other]==final
    assert result['final_contamination']['test']=='integrated-earlier-pr'
    assert result['contamination']['test']=='all-three-pass'
    assert pipeline.graph_summary([result])['head_kind']=={'final-head':{'pairs':0,'ready':0},'pre-update':{'pairs':1,'ready':1}}


@pytest.mark.parametrize('kind',['direct-pr-merge','candidate-not-pr','candidate-patch-overlap'])
def test_r2c_rejects_other_merges_missing_pr_membership_or_any_b2_failure(repo,kind):
    g,D,A,B,C=independent(repo)
    repo.checkout('B')
    if kind=='candidate-patch-overlap':repo.git('cherry-pick',A);B=g.text('rev-parse','HEAD')
    repo.git('merge','--no-ff','--no-edit','A' if kind=='direct-pr-merge' else 'main');final=g.text('rev-parse','HEAD')
    commits=[final] if kind=='candidate-not-pr' else [B,final]
    with pytest.raises(graph.Unresolved):graph.pre_update_head(g,A,final,D,C,'A',C,commits)


def test_non_rate_4xx_with_retry_after_does_not_stop_cohort(tmp_path):
    client,calls,waits=fake_client(tmp_path,[response(404,{'Retry-After':'999'}),response()])
    with pytest.raises(Incomplete):client.get('repos/example/repo/pulls')
    assert not client.stopped and waits==[]
    client.get('repos/other/repo/pulls');assert len(calls)==2


@pytest.mark.parametrize('status',[500,501,503,504])
def test_all_5xx_are_transport_retries(tmp_path,status):
    client,calls,waits=fake_client(tmp_path,[response(status),response()])
    client.get('repos/example/repo/pulls');assert len(calls)==2 and waits==[1]


def test_rate_retry_after_http_date_and_primary_reset(tmp_path):
    client,calls,waits=fake_client(tmp_path,[response(429,{'Retry-After':'Thu, 01 Jan 1970 00:16:45 GMT'}),response()])
    client.get('repos/example/repo/pulls');assert len(calls)==2 and waits==[5]


def test_retry_journal_still_exists_after_unhandled_process_failure(tmp_path):
    calls=[]
    def crash(*a,**kw):calls.append(1);raise KeyboardInterrupt()
    client=GhGet(Permit(),tmp_path,crash,version_reader=lambda:'synthetic gh',wait=lambda n:None)
    with pytest.raises(KeyboardInterrupt):client.get('repos/example/repo/pulls')
    assert len(list(tmp_path.glob('*.request.json')))==1 and not list(tmp_path.glob('*.result.json'))
    restored=GhGet(Permit(),tmp_path,lambda *a,**kw:pytest.fail('Never silently retry an interrupted operation'),version_reader=lambda:'synthetic gh')
    with pytest.raises(Incomplete):restored.get('repos/example/repo/pulls')


def test_global_rate_limit_stops_collector_but_local_page_failure_does_not(monkeypatch):
    from benchmarks.s17b.http import RateLimited
    calls=[]
    class Client:
        calls=1;log=[];stop_reason='acquisition-incomplete-rate-limited'
        def get(self,endpoint):calls.append(endpoint);raise RateLimited()
    result=collect.collect_metadata(Client(),policy())
    assert len(calls)==1 and result['repositories'][1]['status']=='unattempted'
    assert result['global_stop_reason']=='acquisition-incomplete-rate-limited'


def test_metadata_prefix_failure_continues_next_repository_with_selection_intact(monkeypatch):
    class Client:
        calls=0;log=[]
        def get(self,endpoint):
            if '/commits/' in endpoint:return SimpleNamespace(body={'sha':'a'*40})
            return SimpleNamespace(body={'private':False,'id':1,'default_branch':'main'})
    monkeypatch.setattr(collect,'list_closed',lambda *a:{'items':[]})
    walked=[]
    def select(*args):
        walked.append(1)
        return {'selected':[{'slot':1}],'stop_reason':'acquisition-incomplete' if len(walked)==1 else 'cap'}
    monkeypatch.setattr(collect,'select_pairs',select)
    result=collect.collect_metadata(Client(),policy())
    assert len(walked)==2 and result['selected_pairs']==2
    assert result['repositories'][0]['selection']['selected']==[{'slot':1}]
    assert result['repositories'][0]['status']=='acquisition-incomplete'
    assert result['repositories'][1]['status']=='metadata-only' and not result['complete']


def test_r2c_no_additional_nondefault_contamination_ingress(repo):
    g,D,A,B,C=independent(repo)
    repo.checkout('B');repo.git('merge','--no-ff','--no-edit','main');updated=g.text('rev-parse','HEAD')
    repo.branch('other-pr',C);repo.checkout('other-pr');repo.write('unrelated.txt','other PR');extra=repo.commit('other branch')
    repo.checkout('B');repo.git('merge','--no-ff','--no-edit','other-pr');final=g.text('rev-parse','HEAD')
    with pytest.raises(graph.Unresolved,match='nondefault-contamination-ingress'):
        graph.pre_update_head(g,A,final,D,C,'A',C,[B,updated,final])


def test_r2a_plain_auth_failure_and_malformed_response_never_retry(tmp_path):
    for name,event in [('auth',response(401)),('malformed',SimpleNamespace(returncode=0,stdout='HTTP/2.0 200 OK\n\nnot JSON',stderr=''))]:
        client,calls,waits=fake_client(tmp_path/name,[event])
        with pytest.raises(Incomplete):client.get('repos/example/repo/pulls')
        assert len(calls)==1 and waits==[]


def test_round1_selection_m3_anchor_and_b2_bytes_unchanged():
    import ast,hashlib
    from benchmarks.s17b.checkpoint import ROOT
    # SHA256 baselines independently read from committed round 1 (89df440).
    # Keep this test runnable from a clean source export without .git.
    source=(ROOT/'benchmarks/s17b/graph.py').read_text();tree=ast.parse(source)
    expected={'anchor': 'da803f8c03b716450c0f8ca4f709988dc4a6b0aac19be72c46f1aa408dc13eea', 'own_bases': 'd0ba968d295b08d2dc5efe7ab31f945554dbd2fc4f8313ffeffffb0d6165104e', 'contamination': 'da2466caacdd3f3f7bb9e4faa52f930179b653b62e6963efcb399d5aac1d1fb8'}
    for name,wanted in expected.items():
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
        assert hashlib.sha256(ast.get_source_segment(source,node).encode()).hexdigest()==wanted
    files={'benchmarks/s17b/selection.py': 'ec2150b2f1cd1f3d9e8adff86010d08f4cacc8879cc292e582a08e772d84dc40', 'benchmarks/s17/m3.py': 'f9c64ecbfa9a7939303b697287a317ba84cf72d3ad23d86f17832e839f3ae5b5'}
    for relative,wanted in files.items():assert hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()==wanted


def test_commit_list_retries_use_commit_budget_not_metadata(tmp_path):
    configured=policy();configured['per_repository_commits_get_budget']=1
    class Limited:
        def verify(self):return configured
    calls=[];client=GhGet(Limited(),tmp_path,lambda *a,**kw:(calls.append(a) or response(503)),version_reader=lambda:'synthetic gh',wait=lambda n:None)
    from benchmarks.s17b.selection import RepositoryCeiling
    with pytest.raises(RepositoryCeiling):client.get('repos/example/repo/pulls/1/commits')
    assert client.calls==len(calls)==1
    client.runner=lambda *a,**kw:(calls.append(a) or response())
    client.get('repos/example/repo/pulls/1/files');assert client.calls==2


def test_third_rate_limit_attempt_honors_cooldown_but_never_attempts_fourth(tmp_path):
    client,calls,waits=fake_client(tmp_path,[response(429,{'Retry-After':'1'})]*3+[response()])
    with pytest.raises(Incomplete):client.get('repos/example/repo/pulls')
    assert len(calls)==3 and waits==[1,1,1] and not client.stopped
    client.get('repos/other/repo/pulls');assert len(calls)==4


def test_r2c_unchanged_final_head_gets_separate_stratum(repo,monkeypatch):
    g,D,A,B,C=independent(repo)
    monkeypatch.setattr(pipeline,'fetch_head',lambda graph,n,expected,*a:expected)
    slot={'A':1,'B':2,'slot':1,'rank':1,'hash':'a'*64,'details':{
        'A':{'state':'closed','created_at':'2024-01-01T00:00:00Z','closed_at':'2025-02-01T00:00:00Z','merged_at':'2025-02-01T00:00:00Z','merge_commit_sha':C,'head':{'sha':A},'commits':1},
        'B':{'state':'closed','created_at':'2024-01-01T00:00:00Z','closed_at':'2025-03-01T00:00:00Z','head':{'sha':B},'commits':1}}}
    metadata=SimpleNamespace(commits=lambda n,count:([A if n==1 else B],[]))
    result=pipeline.prepare_pair(slot,g,C,metadata,Permit(),None,None)
    assert result['status']=='ready' and result['head_kind']=='final-head' and 'head_adjustment' not in result
    assert pipeline.graph_summary([result])['head_kind']['final-head']=={'pairs':1,'ready':1}
