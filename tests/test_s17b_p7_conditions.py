"""P7 review conditions: global ceilings, immutable lineage and wait recovery."""
from copy import deepcopy
import hashlib,json
from pathlib import Path
from types import SimpleNamespace

import pytest

from benchmarks.s17b import acquire,checkpoint,collect
from benchmarks.s17b.http import RateLimited
from benchmarks.s17b.selection import Ceiling
from .test_s17b_round2 import policy,response


def test_global_pair_cap_stops_cohort_and_preserves_incremental_failure(tmp_path,monkeypatch):
 calls=[]
 class Client:
  calls=0;log=[]
  def get(self,endpoint):
   calls.append(endpoint)
   return SimpleNamespace(body={'sha':'a'*40} if '/commits/' in endpoint else {'id':1,'private':False,'default_branch':'main'})
 configured=policy();configured['maximum_pairs']=1
 monkeypatch.setattr(collect,'list_closed',lambda *args:{'items':[]})
 monkeypatch.setattr(collect,'select_pairs',lambda *args:{'selected':[1,2],'stop_reason':'cap'})
 path=tmp_path/'metadata.json';result=collect.collect_metadata(Client(),configured,metadata_path=path)
 assert not result['complete'] and result['repositories'][1]['status']=='unattempted'
 assert result['repositories'][0]['reason']=='Global pair cap exceeded'
 assert not any('other/repo' in endpoint for endpoint in calls)
 assert json.loads(path.read_text())==result


@pytest.mark.parametrize('kind',['GET','transfer','wait'])
def test_global_request_transfer_wait_ceilings_stop_next_repository(tmp_path,kind):
 calls=[];configured=policy()
 class Permit:
  def verify(self):return configured
 http=acquire.GhGet(Permit(),tmp_path,lambda *a,**kw:pytest.fail('No network'),version_reader=lambda:configured['gh_version'])
 if kind=='GET':configured['maximum_get_requests']=0
 if kind=='wait':
  http.wait_budget_used=900
  http.log=[{'request':1,'endpoint':'repos/example/repo','checkpoint_sha256':'synthetic-test-only'}]
 class Client:
  calls=0;log=[]
  def get(self,endpoint):
   calls.append(endpoint)
   if kind=='GET':return http.get(endpoint)
   if kind=='wait':http._pause(1)
   budget=acquire.GitBudget(1);budget.account(acquire.FetchReceipt('a'*40,2))
 result=collect.collect_metadata(Client(),configured)
 assert not result['complete'] and result['repositories'][1]['status']=='unattempted'
 assert len(calls)==1


def predecessor():
 names=['benchmarks/s17b/selection.py','benchmarks/s17b/graph.py','benchmarks/s17b/pipeline.py',
        'benchmarks/s17/m3.py','benchmarks/s17/matching.py','benchmarks/mut_v05_m2_audit.py']
 return {'policy':policy(),'code_sha256':{name:'same' for name in names}}


def successor(prior):
 raw=json.dumps(prior);new=deepcopy(prior)
 new['predecessor']={'bytes':raw,'sha256':hashlib.sha256(raw.encode()).hexdigest()}
 return new


@pytest.mark.parametrize('key',sorted(k for k in policy()['apparatus'] if k!='resume'))
def test_lineage_refuses_each_non_resume_apparatus_field(key):
 new=successor(predecessor());new['policy']['apparatus'][key]={'changed':True}
 with pytest.raises(ValueError,match='apparatus'):checkpoint.lineage(new)


@pytest.mark.parametrize('section,key,value',[
 ('pr_isolation','maximum_failed_prs_per_repository',6),
 ('pre_update_heads','enabled',False),('transport','max_attempts',2)])
def test_lineage_refuses_selecting_nested_apparatus_changes(section,key,value):
 new=successor(predecessor());new['policy']['apparatus'][section][key]=value
 with pytest.raises(ValueError,match='apparatus'):checkpoint.lineage(new)


@pytest.mark.parametrize('name',['benchmarks/s17/matching.py','benchmarks/mut_v05_m2_audit.py'])
def test_lineage_refuses_raw_or_corrected_m2_change(name):
 new=successor(predecessor());new['code_sha256'][name]='changed'
 with pytest.raises(ValueError,match='Protected predecessor'):checkpoint.lineage(new)


def test_lineage_permits_only_resume_apparatus_update():
 new=successor(predecessor());new['policy']['apparatus']['resume']['fixture_note']='changed resume wiring'
 assert checkpoint.lineage(new)=={new['predecessor']['sha256']}


def test_interrupted_wait_retains_one_reservation_across_multiple_restarts(tmp_path):
 configured=policy()
 class Permit:
  def verify(self):return configured
 def interrupted(seconds):raise KeyboardInterrupt()
 first=acquire.GhGet(Permit(),tmp_path,lambda *a,**kw:response(429,{'Retry-After':'300'}),version_reader=lambda:configured['gh_version'],clock=lambda:1000,wait=interrupted)
 with pytest.raises(KeyboardInterrupt):first.get('repos/example/repo/pulls/1')
 second=acquire.GhGet(Permit(),tmp_path,lambda *a,**kw:pytest.fail('Cooldown interrupted before GET'),version_reader=lambda:configured['gh_version'],clock=lambda:1000,wait=interrupted)
 with pytest.raises(KeyboardInterrupt):second.get('repos/other/repo/pulls')
 assert second.wait_budget_used==300
 waits=[]
 third=acquire.GhGet(Permit(),tmp_path,lambda *a,**kw:response(),version_reader=lambda:configured['gh_version'],clock=lambda:1000,wait=waits.append)
 third.get('repos/other/repo/pulls')
 assert third.wait_budget_used==300 and sum(waits)==300
 assert third.total_wait_seconds==300
 assert len(list(tmp_path.glob('*.wait-started.json')))==1
 assert len(list(tmp_path.glob('*.wait-result.json')))==1
 fourth=acquire.GhGet(Permit(),tmp_path,lambda *a,**kw:pytest.fail('No new GET'),version_reader=lambda:pytest.fail('Cache first'),clock=lambda:1000)
 fourth.get('repos/other/repo/pulls')
 assert fourth.wait_budget_used==300 and fourth.total_wait_seconds==300


def test_missing_m2_pin_in_unknown_predecessor_is_refused():
 prior=predecessor();del prior['code_sha256']['benchmarks/s17/matching.py']
 new=successor(prior);new['code_sha256']['benchmarks/s17/matching.py']='same'
 with pytest.raises(ValueError,match='Protected predecessor'):checkpoint.lineage(new)


def test_real_round2_legacy_m2_compatibility_is_hash_scoped_when_evidence_present():
 path=Path('~/.crosswire-evidence/s17b-r2/checkpoint-1.json').expanduser()
 if not path.is_file():pytest.skip('Original round-2 checkpoint absent locally')
 raw=path.read_text();assert hashlib.sha256(raw.encode()).hexdigest()==checkpoint.LEGACY_ROUND2_CHECKPOINT
 prior=json.loads(raw)
 current={'policy':json.loads((checkpoint.ROOT/'benchmarks/s17b/policy.json').read_text()),
          'code_sha256':checkpoint.graph_pins(),
          'predecessor':{'bytes':raw,'sha256':checkpoint.LEGACY_ROUND2_CHECKPOINT}}
 assert checkpoint.lineage(current)=={checkpoint.LEGACY_ROUND2_CHECKPOINT}
 for name in checkpoint.LEGACY_M2_PINS:
  changed=deepcopy(current);changed['code_sha256'][name]='changed'
  with pytest.raises(ValueError,match='Protected predecessor'):checkpoint.lineage(changed)
 # Same parsed policy/code with different predecessor bytes is not the one
 # audited legacy checkpoint and cannot borrow its missing M2 pins.
 current['predecessor']['bytes']=raw+' '
 current['predecessor']['sha256']=hashlib.sha256((raw+' ').encode()).hexdigest()
 with pytest.raises(ValueError,match='Protected predecessor'):checkpoint.lineage(current)
