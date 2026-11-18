"""P7 acquisition-only resume: fake transports and local cache bytes, no API."""
from copy import deepcopy
import hashlib,json
from pathlib import Path
from types import SimpleNamespace

import pytest

from benchmarks.s17b import acquire,collect,entry,checkpoint
from .test_s17b_round2 import policy,response
from .test_s17b_selection import pr


class Permit:
 def verify(self):return policy()


def client(tmp_path,runner,**kwargs):
 return acquire.GhGet(Permit(),tmp_path,runner,version_reader=lambda:'synthetic gh',wait=lambda n:None,**kwargs)


def test_numeric_pagination_bound_to_verified_policy_repository_and_budget(tmp_path):
 calls=[]
 def runner(args,**kwargs):
  calls.append(args[-1])
  if args[-1]=='repos/example/repo':return response(body={'id':34739117,'private':False,'full_name':'example/repo'})
  if '?page=2' in args[-1]:return response(body=[])
  return response(headers={'Link':'<https://api.github.com/repositories/34739117/pulls?page=2>; rel="next"'},body=[pr(1)])
 c=client(tmp_path,runner);c.get('repos/example/repo')
 listing=acquire.list_closed(c,'example/repo',policy()['terminal_lower'])
 assert listing['total_pages']==2 and len(calls)==3
 assert c.log[-1]['repository']=='example/repo' and c.log[-1]['endpoint_class']=='metadata'
 assert c.log[-1]['endpoint']=='repositories/34739117/pulls?page=2'
 c.get('repositories/34739117/pulls/1/commits');assert c.log[-1]['endpoint_class']=='commits'


@pytest.mark.parametrize('bad',['repositories/999/pulls','repositories/34739117/../pulls','repositories/34739117//pulls','repositories/%3334739117/pulls'])
def test_foreign_or_malformed_numeric_id_never_reaches_transport(tmp_path,bad):
 calls=[];c=client(tmp_path,lambda *a,**kw:(calls.append(1) or response(body={'id':34739117,'private':False})))
 c.get('repos/example/repo')
 with pytest.raises(ValueError):c.get(bad)
 assert len(calls)==1


def test_unpinned_numeric_id_is_not_authority(tmp_path):
 c=client(tmp_path,lambda *a,**kw:pytest.fail('No GET for unpinned numeric ID'))
 with pytest.raises(ValueError):c.get('repositories/34739117/pulls')


def test_exception_isolated_and_metadata_durable_before_next_repository(tmp_path,monkeypatch):
 snapshot=tmp_path/'metadata.json'
 class Client:
  calls=0;log=[]
  def get(self,endpoint):
   if endpoint=='repos/other/repo':
    saved=json.loads(snapshot.read_text());assert saved['repositories'][0]['exception_class']=='RuntimeError'
   if '/commits/' in endpoint:return SimpleNamespace(body={'sha':'a'*40})
   return SimpleNamespace(body={'private':False,'id':1,'default_branch':'main'})
 def listing(c,repo,lower):
  if repo=='example/repo':raise RuntimeError('injected list bug')
  return {'items':[]}
 monkeypatch.setattr(collect,'list_closed',listing)
 result=collect.collect_metadata(Client(),policy(),metadata_path=snapshot)
 assert not result['complete'] and result['repositories'][1]['status']=='metadata-only'
 assert result['repositories'][0]['exception_class']=='RuntimeError'
 assert 'RuntimeError: injected list bug' in result['repositories'][0]['traceback']
 assert json.loads(snapshot.read_text())==result


def test_resume_145_cached_requests_same_order_no_version_or_network_runner(tmp_path):
 original=[]
 def runner(args,**kwargs):original.append(args[-1]);return response(body=[])
 first=client(tmp_path,runner)
 # 145 synthetic request records model the real successful prefix; each class
 # stays within its nonrolling allocation (100 metadata +45 commit lists).
 endpoints=['repos/example/repo/pulls/'+str(n) for n in range(1,101)]+['repos/example/repo/pulls/'+str(n)+'/commits' for n in range(1,46)]
 for endpoint in endpoints:first.get(endpoint)
 replay=acquire.GhGet(Permit(),tmp_path,lambda *a,**kw:pytest.fail('Cached prefix must not invoke gh'),version_reader=lambda:pytest.fail('Replay precedes version probe'))
 for endpoint in endpoints:replay.get(endpoint)
 assert replay.calls==145 and original==endpoints
 assert replay.replay_order==endpoints
 assert len(list(tmp_path.glob('*.request.json')))==145


def test_missing_request_only_is_issued_after_cache_replay(tmp_path):
 first=client(tmp_path,lambda *a,**kw:response(body=['cached']))
 first.get('repos/example/repo/pulls/1')
 calls=[];resumed=client(tmp_path,lambda args,**kw:(calls.append(args[-1]) or response(body=['new'])))
 assert resumed.get('repos/example/repo/pulls/1').body==['cached']
 assert resumed.get('repos/example/repo/pulls/2').body==['new']
 assert calls==['repos/example/repo/pulls/2'] and resumed.calls==2


def test_uncertain_started_request_charges_budget_and_resumes_within_three_total_attempts(tmp_path):
 def crash(*a,**kw):raise KeyboardInterrupt()
 first=client(tmp_path,crash)
 with pytest.raises(KeyboardInterrupt):first.get('repos/example/repo/pulls/1')
 calls=[];resumed=client(tmp_path,lambda *a,**kw:(calls.append(1) or response()))
 resumed.get('repos/example/repo/pulls/1')
 assert len(calls)==1 and resumed.calls==2
 assert resumed.log[0]['outcome']=='interrupted-unconfirmed' and resumed.log[1]['operation_attempt']==2


def test_successful_entry_resume_is_idempotent_no_new_transport(tmp_path,monkeypatch):
 from .test_s17b_entry import adapters
 root=tmp_path/'round';runner,transport,calls,transfers,_=adapters(monkeypatch,root)
 configured=deepcopy(__import__('tests.test_s17b_entry',fromlist=['policy']).policy())
 configured['apparatus']={'resume':{'enabled':True}}
 monkeypatch.setattr(checkpoint.Permit,'verify',lambda self:deepcopy(configured))
 permit=checkpoint.Permit(tmp_path/'absent',tmp_path/'absent')
 first=entry.acquire(permit,root,runner=runner,transport=transport)
 second=entry.acquire(permit,root,runner=lambda *a,**kw:pytest.fail('No new command'),transport=lambda *a,**kw:pytest.fail('No new fetch'))
 assert second==first
 assert len(list((root/'attempts').glob('*.started.json')))==2


def test_numeric_requests_share_named_metadata_sub_budget(tmp_path):
 configured=policy();configured['per_repository_metadata_get_budget']=2
 class Bound:
  def verify(self):return configured
 c=acquire.GhGet(Bound(),tmp_path,lambda args,**kw:response(body={'id':7,'private':False}) if args[-1]=='repos/example/repo' else response(),version_reader=lambda:'synthetic gh')
 c.get('repos/example/repo');c.get('repositories/7/pulls')
 from benchmarks.s17b.selection import RepositoryCeiling
 with pytest.raises(RepositoryCeiling):c.get('repos/example/repo/pulls/1')
 c.get('repositories/7/pulls/1/commits')
 assert c.calls==3


def test_predecessor_lineage_exact_bytes_policy_and_protected_code():
 from benchmarks.s17b.checkpoint import lineage
 protected=list(checkpoint.PROTECTED_CODE)
 prior={'policy':policy(),'code_sha256':{name:'same' for name in protected}}
 raw=json.dumps(prior)
 successor=deepcopy(prior);successor['policy']['apparatus']['resume']['fixture_note']='changed apparatus'
 successor['predecessor']={'bytes':raw,'sha256':hashlib.sha256(raw.encode()).hexdigest()}
 assert lineage(successor)=={hashlib.sha256(raw.encode()).hexdigest()}
 for field in ('pair_order_seed','detector_commit','round_id'):
  changed=deepcopy(successor);changed['policy'][field]='changed'
  with pytest.raises(ValueError,match='selection policy'):lineage(changed)
 changed=deepcopy(successor);changed['code_sha256'][protected[0]]='different'
 with pytest.raises(ValueError,match='Protected predecessor'):lineage(changed)
 changed=deepcopy(successor);changed['predecessor']['bytes']+=' '
 with pytest.raises(ValueError,match='hash drift'):lineage(changed)


def test_foreign_checkpoint_cache_cannot_be_reused(tmp_path):
 c=client(tmp_path,lambda *a,**kw:response());c.get('repos/example/repo/pulls')
 path=next(tmp_path.glob('*.request.json'));value=json.loads(path.read_text());value['checkpoint_sha256']='foreign';path.write_text(json.dumps(value))
 # Result provenance must be checked against its matching claim too.
 result=path.with_name(path.name.replace('.request.json','.result.json'));value=json.loads(result.read_text());value['checkpoint_sha256']='foreign';result.write_text(json.dumps(value))
 resumed=client(tmp_path,lambda *a,**kw:pytest.fail('No foreign-checkpoint transport'))
 with pytest.raises(acquire.Incomplete,match='checkpoint'):resumed.get('repos/example/repo/pulls')


def test_fetch_journal_restores_total_without_refetch_and_stops_unknown_partial(tmp_path):
 from benchmarks.s17b.resume import FetchJournal
 from benchmarks.s17b.acquire import GitBudget,FetchReceipt
 root=tmp_path;budget=GitBudget(20);calls=[]
 first=FetchJournal(root,lambda *a,**kw:(calls.append(1) or FetchReceipt('a'*40,7)),budget,'pin',{'pin'})
 args=['git','fetch','origin','refs/pull/1/head'];receipt=first(args,cwd=root/'clones/example/repo',maximum_bytes=20);budget.account(receipt)
 second_budget=GitBudget(20);second=FetchJournal(root,lambda *a,**kw:pytest.fail('No duplicate fetch'),second_budget,'pin',{'pin'})
 cached=second(args,cwd=root/'clones/example/repo',maximum_bytes=13);second_budget.account(cached)
 assert second_budget.used==7 and calls==[1] and cached.transferred_bytes==0
 unknown=tmp_path/'unknown';unknown.mkdir();bad=FetchJournal(unknown,lambda *a,**kw:(_ for _ in ()).throw(KeyboardInterrupt()),GitBudget(),'pin',{'pin'})
 with pytest.raises(KeyboardInterrupt):bad(args,cwd=unknown/'clone',maximum_bytes=10)
 with pytest.raises(acquire.Ceiling,match='interrupted fetch'):FetchJournal(unknown,None,GitBudget(),'pin',{'pin'})


def test_actual_round2_145_cache_order_offline_when_evidence_available(tmp_path):
 """D-Ev1 optional local audit; no operational checkpoint/authorization is made."""
 import os,shutil
 evidence=Path(os.environ.get('CROSSWIRE_EVIDENCE_DIR','~/.crosswire-evidence/s17b-r2')).expanduser()
 invocation=evidence/'acquisition-invocation.json'
 raw_cache=Path(json.loads(invocation.read_text())['root'])/'requests' if invocation.is_file() else None
 if (evidence/'checkpoint-2-material').is_dir():evidence=evidence/'checkpoint-2-material'
 cache=evidence/'acquisition/requests'
 if not cache.is_dir():pytest.skip('Round-2 external response archive not extracted locally')
 recovered=evidence/'metadata-recovered.json'
 if not recovered.is_file():pytest.skip('Round-2 offline recovery ledger absent')
 expected=json.loads(recovered.read_text())
 shutil.copytree(raw_cache if raw_cache and raw_cache.is_dir() else cache,tmp_path/'requests')
 if not (raw_cache and raw_cache.is_dir()):
  # Portable artifact JSON is re-serialized; rebind transport hashes in this
  # disposable synthetic copy only. Original raw and archive bytes stay intact.
  for result in (tmp_path/'requests').glob('*.result.json'):
   value=json.loads(result.read_text())
   response_path=tmp_path/'requests'/(hashlib.sha256(value['endpoint'].encode()).hexdigest()+'.json')
   value['response_sha256']=hashlib.sha256(response_path.read_bytes()).hexdigest()
   result.write_text(json.dumps(value))
 configured=json.loads((Path(__file__).parents[1]/'benchmarks/s17b/policy.json').read_text())
 class Bound:
  def verify(self):return configured
  def cache_checkpoints(self):return {v['checkpoint_sha256'] for v in expected['request_ledger']}
 class Missing(BaseException):pass
 new=[]
 def forbidden(args,**kw):
  if args[:2]==['gh','--version']:return SimpleNamespace(stdout=configured['gh_version']+'\n')
  new.append(args[-1]);raise Missing()
 c=acquire.GhGet(Bound(),tmp_path/'requests',forbidden)
 with pytest.raises(Missing):collect.collect_metadata(c,configured)
 assert c.replay_order==[v['endpoint'] for v in expected['request_ledger']]
 assert len(c.replay_order)==145
 assert new==['repositories/34739117/pulls?direction=desc&per_page=100&sort=updated&state=closed&page=2']
 # Only a synthetic missing-request claim exists; no real GET was performed.
 assert c.calls==146


def test_exhausted_failure_keeps_original_http_cause_without_new_get_on_resume(tmp_path):
 first=client(tmp_path,lambda *a,**kw:response(404))
 m=acquire.Metadata(first,'example/repo',policy(),'main');m.load(59)
 second=client(tmp_path,lambda *a,**kw:pytest.fail('No re-request of permanent 404'))
 m=acquire.Metadata(second,'example/repo',policy(),'main');stub=m.load(59)
 assert stub['_metadata_unavailable']['http_status']==404
 assert stub['_metadata_unavailable']['exit_status']==1 and second.calls==1


def test_corrupted_cached_body_cannot_reset_budget_or_trigger_transport(tmp_path):
 c=client(tmp_path,lambda *a,**kw:response());c.get('repos/example/repo/pulls')
 key='repos/example/repo/pulls';path=tmp_path/(hashlib.sha256(key.encode()).hexdigest()+'.json')
 value=json.loads(path.read_text());value['body']=['tampered'];path.write_text(json.dumps(value))
 replay=client(tmp_path,lambda *a,**kw:pytest.fail('No transport after cache corruption'))
 with pytest.raises(acquire.Ceiling,match='hash drift'):replay.get(key)


def test_incremental_snapshot_survives_controller_interrupt(tmp_path,monkeypatch):
 snapshot=tmp_path/'metadata.json'
 class Interrupted(BaseException):pass
 class Client:
  calls=0;log=[]
  def get(self,endpoint):
   if endpoint=='repos/other/repo':raise Interrupted()
   return SimpleNamespace(body={'sha':'a'*40} if '/commits/' in endpoint else {'id':1,'private':False,'default_branch':'main'})
 monkeypatch.setattr(collect,'list_closed',lambda *a:{'items':[]})
 with pytest.raises(Interrupted):collect.collect_metadata(Client(),policy(),metadata_path=snapshot)
 value=json.loads(snapshot.read_text());assert len(value['repositories'])==1 and value['repositories'][0]['status']=='metadata-only'


def test_fresh_prefix_and_resume_have_identical_selection(tmp_path):
 def runner(args,**kw):
  parts=args[-1].split('?',1)[0].split('/')
  if len(parts)==3:return response(body={'id':1 if parts[1]=='example' else 2,'private':False,'default_branch':'main'})
  if parts[3]=='commits':return response(body={'sha':'a'*40})
  if len(parts)==4:return response(body=[pr(1),pr(2)] if parts[1]=='example' else [])
  n=int(parts[4]);v=pr(n)
  if parts[3]=='issues':return response(body=v['_timeline'])
  if len(parts)==5:return response(body=v)
  return response(body=v['_files'])
 first=client(tmp_path,runner);a=collect.collect_metadata(first,policy())
 second=client(tmp_path,lambda *a,**kw:pytest.fail('All responses already cached'))
 b=collect.collect_metadata(second,policy())
 assert [r['selection'] for r in a['repositories']]==[r['selection'] for r in b['repositories']]
 assert a['get_requests']==b['get_requests']


def test_numeric_link_to_another_listed_repository_is_rejected_in_active_walk(tmp_path):
 def runner(args,**kw):return response(body={'id':1 if args[-1]=='repos/example/repo' else 2,'private':False})
 c=client(tmp_path,runner);c.get('repos/example/repo');c.get('repos/other/repo')
 c.active_repository='example/repo'
 with pytest.raises(ValueError,match='another repository walk'):c.get('repositories/2/pulls')
 assert c.calls==2
