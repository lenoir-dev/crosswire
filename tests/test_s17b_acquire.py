"""Synthetic GET pages and fetch receipts; real networks/fetch are never used."""
from copy import deepcopy
from types import SimpleNamespace
import json

import pytest

from benchmarks.s17b.acquire import Page,pages,list_closed,Metadata,GhGet,GitBudget,FetchReceipt,fetch_head,ObjectStoreTransport
from benchmarks.s17b.selection import Incomplete,Ceiling
from .test_s17b_selection import pr


class Client:
    def __init__(self,pages):self.pages=pages;self.calls=[]
    def get(self,endpoint,**parameters):self.calls.append((endpoint,parameters));return self.pages[endpoint]


def link(endpoint):return {'link':f'<https://api.github.com/{endpoint}>; rel="next"'}


def item(n,updated='2021-12-01T00:00:00Z',end='2021-11-01T00:00:00Z'):
    return pr(n,created_at='2021-01-01T00:00:00Z',closed_at=end,updated_at=updated)


def test_closed_pagination_reads_one_additional_full_tail_page():
    endpoint='repos/example/repo/pulls'
    client=Client({endpoint:Page([item(1)],link(endpoint+'?page=2')),
                   endpoint+'?page=2':Page([item(n) for n in range(2,102)],link(endpoint+'?page=3'))})
    result=list_closed(client,'example/repo','2022-01-01T00:00:00Z')
    assert result['total_pages']==2 and result['tail_sampled']
    assert not result['exhausted'] and result['final_link']
    assert client.calls[0][1]['state']=='closed'


def test_tail_violation_forces_endpoint_exhaustion():
    endpoint='repos/example/repo/pulls'
    client=Client({endpoint:Page([item(1)],link(endpoint+'?page=2')),
      endpoint+'?page=2':Page([item(2,end='2025-01-01T00:00:00Z')],link(endpoint+'?page=3')),
      endpoint+'?page=3':Page([item(3)])})
    result=list_closed(client,'example/repo','2022-01-01T00:00:00Z')
    assert result['total_pages']==3 and result['tail_violations']==1 and result['exhausted']


def test_missing_page_or_untrusted_next_is_not_completeness():
    client=Client({'start':Page([],{'link':'<https://evil.invalid/page>; rel="next"'})})
    with pytest.raises(Incomplete):pages(client,'start')


def test_metadata_files_rename_and_timeline_are_cached_and_complete():
    prefix='repos/example/repo/pulls/3';detail=pr(3);detail.pop('_files');detail.pop('_timeline')
    client=Client({prefix:Page(detail),prefix+'/files':Page([{'filename':'renamed.txt','previous_filename':'old.py'}]),
                   'repos/example/repo/issues/3/timeline':Page([])})
    metadata=Metadata(client,'example/repo');value=metadata.load(3)
    assert value['_files_complete'] and metadata.load(3) is value
    assert len(client.calls)==3


def test_pr_commit_truncation_is_post_metadata_unresolved():
    endpoint='repos/example/repo/pulls/3/commits'
    metadata=Metadata(Client({endpoint:Page([{'sha':'a'*40}])}),'example/repo')
    with pytest.raises(Incomplete,match='incomplete'):metadata.commits(3,251)


class Permit:
    def verify(self):return {'maximum_get_requests':1,'api_version':'synthetic-only','gh_version':'synthetic gh'}


def test_get_is_explicit_get_cached_and_limited_without_real_gh(tmp_path):
    calls=[]
    def runner(args,**kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0,stdout='HTTP/2.0 200 OK\r\nETag: test\r\nX-RateLimit-Remaining: 10\r\n\r\n[]')
    client=GhGet(Permit(),tmp_path,runner,version_reader=lambda:'synthetic gh')
    assert client.get('repos/example/repo/pulls').body==[]
    client.get('repos/example/repo/pulls')
    assert len(calls)==1 and calls[0][2:4]==['--method','GET']
    with pytest.raises(Ceiling):client.get('repos/example/repo/pulls/1')
    assert 'authorization' not in next(tmp_path.glob('*.json')).read_text().lower()


def test_gh_version_mismatch_precedes_get(tmp_path):
    with pytest.raises(ValueError,match='version differs'):
        GhGet(Permit(),tmp_path,lambda *a,**kw:pytest.fail('GET forbidden'),version_reader=lambda:'different gh').get('rate_limit')


def test_request_budget_and_cached_response_survive_client_restart(tmp_path):
    def runner(*args,**kw):return SimpleNamespace(returncode=0,stdout='HTTP/2.0 200 OK\n\n[]')
    first=GhGet(Permit(),tmp_path,runner,version_reader=lambda:'synthetic gh')
    first.get('repos/example/repo/pulls')
    second=GhGet(Permit(),tmp_path,lambda *a,**kw:pytest.fail('No second GET allowed'),version_reader=lambda:'synthetic gh')
    assert second.get('repos/example/repo/pulls').body==[]
    with pytest.raises(Ceiling):second.get('repos/example/repo/pulls/1')


def test_bad_authorization_fails_before_any_transport(tmp_path):
    class Deny:
        def verify(self):raise PermissionError('not authorized')
    def forbidden(*a,**kw):pytest.fail('Network command must not be reached')
    with pytest.raises(PermissionError):GhGet(Deny(),tmp_path,forbidden).get('rate_limit')


def test_fetch_command_uses_only_final_head_and_requires_metered_receipt():
    calls=[];bound=[]
    graph=SimpleNamespace(repo='synthetic-disposable',commit=lambda x:x,bind=lambda *a:bound.append(a))
    def transport(args,**kwargs):calls.append((args,kwargs));return FetchReceipt('a'*40,10)
    budget=GitBudget(11)
    assert fetch_head(graph,7,'a'*40,Permit(),budget,transport)=='a'*40
    assert calls[0][0]==['git','fetch','--no-tags','origin','refs/pull/7/head']
    assert budget.used==10 and bound==[('pr-7','a'*40)]
    with pytest.raises(Ceiling):fetch_head(graph,8,'a'*40,Permit(),budget,transport)


def test_changed_head_is_unlabelled_and_not_silently_updated():
    graph=SimpleNamespace(repo='synthetic-disposable',commit=lambda x:pytest.fail('No stale commit binding'))
    with pytest.raises(Incomplete,match='stale'):
        fetch_head(graph,7,'a'*40,Permit(),GitBudget(),lambda *a,**k:FetchReceipt('b'*40,1))


def test_unmeasurable_fetch_stops_cohort_and_no_next_fetch():
    calls=[];budget=GitBudget()
    graph=SimpleNamespace(repo='synthetic',commit=lambda x:x,bind=lambda *a:None)
    def transport(*a,**kw):calls.append(1);return FetchReceipt('a'*40,None)
    with pytest.raises(Ceiling,match='Unmeasurable'):fetch_head(graph,7,'a'*40,Permit(),budget,transport)
    with pytest.raises(Ceiling):fetch_head(graph,8,'a'*40,Permit(),budget,transport)
    assert calls==[1]


def test_failed_fetch_still_accounts_measured_bytes():
    graph=SimpleNamespace(repo='synthetic',commit=lambda x:x,bind=lambda *a:None);budget=GitBudget(30)
    with pytest.raises(Incomplete,match='unavailable'):
        fetch_head(graph,7,'a'*40,Permit(),budget,lambda *a,**kw:FetchReceipt(None,12,'unavailable'))
    assert budget.used==12


def test_object_store_proxy_counts_packs_once_without_fetch(tmp_path):
    objects=tmp_path/'objects';(objects/'pack').mkdir(parents=True)
    (objects/'pack/data.pack').write_bytes(b'x'*10);(objects/'loose').write_bytes(b'y'*5)
    assert ObjectStoreTransport.store_size(objects)==15
    assert ObjectStoreTransport.store_size(tmp_path/'missing') is None


def test_real_transport_accounting_with_fake_git_process_only(tmp_path):
    objects=tmp_path/'objects';objects.mkdir();(objects/'base').write_bytes(b'x'*2)
    class Allowed:
        def verify(self):return {'repositories':['example/repo']}
    calls=[]
    def runner(args,**kw):
        calls.append(args)
        if args[1:]==['remote','get-url','origin']:value='https://github.com/example/repo.git'
        elif args[1:]==['rev-parse','--git-path','objects']:value='objects'
        elif args[1:]==['rev-parse','FETCH_HEAD^{commit}']:value='a'*40
        elif args[1]=='fetch':
            (objects/'new').write_bytes(b'x'*12)
            return SimpleNamespace(returncode=0,stdout='',stderr='Receiving objects: 100% (1/1), 20 bytes, done.\n')
        else:raise AssertionError(args)
        return SimpleNamespace(returncode=0,stdout=value,stderr='')
    receipt=ObjectStoreTransport(Allowed(),runner)(['git','fetch','--no-tags','origin','refs/pull/7/head'],cwd=tmp_path,maximum_bytes=30)
    assert receipt==FetchReceipt('a'*40,20) # max(growth=12, progress=20), not sum
    assert any('--progress' in args for args in calls)


def test_shrinking_store_is_unmeasurable_and_stops(tmp_path,monkeypatch):
    class Allowed:
        def verify(self):return {'repositories':['example/repo']}
    sizes=iter([20,10])
    transport=ObjectStoreTransport(Allowed(),lambda args,**kw:SimpleNamespace(returncode=0,stdout=(
        'https://github.com/example/repo.git' if args[1]=='remote' else 'objects'),stderr=''))
    monkeypatch.setattr(transport,'store_size',lambda d:next(sizes))
    with pytest.raises(Ceiling,match='Unmeasurable'):
        transport(['git','fetch','origin','refs/pull/1/head'],cwd=tmp_path,maximum_bytes=30)


def test_get_timeout_keeps_request_claim_and_never_retries(tmp_path):
    import subprocess
    def timeout(*a,**kw):raise subprocess.TimeoutExpired('synthetic gh',60)
    client=GhGet(Permit(),tmp_path,timeout,version_reader=lambda:'synthetic gh')
    with pytest.raises(Incomplete):client.get('rate_limit')
    retry=GhGet(Permit(),tmp_path,lambda *a,**kw:pytest.fail('No retry after incomplete request'),version_reader=lambda:'synthetic gh')
    with pytest.raises(Incomplete):retry.get('rate_limit')


def test_nonrolling_repository_get_budget_does_not_starve_next_repository(tmp_path):
    from benchmarks.s17b.selection import RepositoryCeiling
    class Allocated:
        def verify(self):return {'maximum_get_requests':1500,'per_repository_get_budget':1,'gh_version':'synthetic gh','api_version':'test'}
    client=GhGet(Allocated(),tmp_path,lambda *a,**kw:SimpleNamespace(returncode=0,stdout='HTTP/2.0 200 OK\n\n[]'),version_reader=lambda:'synthetic gh')
    client.get('repos/one/repo/pulls')
    with pytest.raises(RepositoryCeiling):client.get('repos/one/repo/pulls/1')
    client.get('repos/two/repo/pulls')
    assert client.calls==2


@pytest.mark.parametrize('failed_stage', ['detail', 'timeline', 'files', None])
def test_r2_metadata_short_circuits_a_before_b(failed_stage):
    from .test_s17b_selection import POLICY
    from benchmarks.s17b.selection import select_pairs
    details={n:pr(n) for n in (1,2)}
    if failed_stage=='detail':details[1]['base']['ref']='other'
    if failed_stage=='timeline':details[1]['_timeline']=[]
    if failed_stage=='files':details[1]['_files']=[{'filename':'README.md'}]
    pages_by_endpoint={}
    for n,d in details.items():
        prefix=f'repos/example/repo/pulls/{n}'
        pages_by_endpoint[prefix]=Page(d)
        pages_by_endpoint[f'repos/example/repo/issues/{n}/timeline']=Page(d['_timeline'])
        pages_by_endpoint[prefix+'/files']=Page(d['_files'])
    client=Client(pages_by_endpoint)
    answer=select_pairs([pr(1),pr(2)],1,'main',POLICY,Metadata(client,'example/repo',POLICY,'main').load)
    expected=['repos/example/repo/pulls/1']
    if failed_stage!='detail':expected+=['repos/example/repo/issues/1/timeline']
    if failed_stage not in ('detail','timeline'):expected+=['repos/example/repo/pulls/1/files']
    if failed_stage is None:expected+=['repos/example/repo/pulls/2','repos/example/repo/issues/2/timeline','repos/example/repo/pulls/2/files']
    assert [e for e,_ in client.calls]==expected
    row=answer['ledger'][0]
    assert row['first_failed_pr']==('A' if failed_stage else None)
    assert row['first_failed_stage']==failed_stage
