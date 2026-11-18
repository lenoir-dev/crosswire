"""Pure synthetic list/metadata tests: no API, fetch, oracle or labels."""
from copy import deepcopy
from datetime import datetime,timezone
import json
from pathlib import Path

import pytest

from benchmarks.s17b.selection import pair_hash,enumerate_pairs,select_pairs,metadata_filter,Ceiling
from benchmarks.s17b.checkpoint import prepare,Permit


POLICY={'pair_order_seed':'s17b-v1','terminal_lower':'2022-01-01T00:00:00Z','collection_cutoff':'2026-01-01T00:00:00Z','pairs_per_repository':20}


def pr(n,**changes):
    value={'number':n,'state':'closed','created_at':'2021-12-01T00:00:00Z','closed_at':'2025-04-01T00:00:00Z','merged_at':None,
           'base':{'ref':'main','repo':{'id':1}},'changed_files':1,'draft':True,
           '_files':[{'filename':'use.py'}],'_timeline':[],'_files_complete':True,'_timeline_complete':True}
    value.update(changes)
    if '_timeline' not in changes:
        value['_timeline']=[{'event':'merged' if value.get('merged_at') else 'closed',
                             'created_at':value.get('merged_at') or value.get('closed_at')}]
    return value


@pytest.mark.parametrize('raw,expected',[
 ('s17b-v1|123456789|4|5','91fbad73416315bd6360c6a6a91935eff18dc9fbdcc0570f30f2405f63486df4'),
 ('s17b-v1|1|1|2','b6da358de0571c50d09606c27f6035a34683751287fe297c8aa2c5baf074ce10'),
 ('s17b-v1|1|2|3','20ac85bfa6ed7b2292f5327fce2f207647775a8a0957053997bf6d7a52293322')])
def test_exact_seed_vectors(raw,expected):
    _,repo,a,b=raw.split('|');assert pair_hash(repo,a,b)==expected


@pytest.mark.parametrize('repo,a,b',[('01',1,2),(1,'01',2),(1,1,'2 '),(1,2,1),(True,1,2)])
def test_noncanonical_hash_inputs_rejected(repo,a,b):
    with pytest.raises(ValueError):pair_hash(repo,a,b)


def test_overlap_touching_is_not_overlap_and_unknown_is_ranked():
    one=pr(1,closed_at='2024-01-01T00:00:00Z')
    two=pr(2,created_at='2024-01-01T00:00:00Z')
    assert enumerate_pairs([one,two],1)[0]==[]
    unknown=pr(3,created_at=None)
    assert enumerate_pairs([one,unknown],1)[0][0]['list_uncertain']


def test_permutation_and_repo_name_do_not_change_rank():
    items=[pr(n) for n in range(1,8)]
    assert enumerate_pairs(items,1)[0]==enumerate_pairs(list(reversed(items)),1)[0]
    assert all(p['hash']==p['hash'].lower() for p in enumerate_pairs(items,1)[0])


def test_terminal_bounds_and_draft_at_close():
    assert metadata_filter(pr(1,closed_at=POLICY['terminal_lower']),'main',POLICY) is None
    assert metadata_filter(pr(1,closed_at=POLICY['collection_cutoff']),'main',POLICY)=='terminal-window'
    assert metadata_filter(pr(1),'main',POLICY) is None
    assert metadata_filter(pr(1,_timeline=[{'event':'reopened'}]),'main',POLICY)=='lifecycle-or-base-changed'
    assert metadata_filter(pr(1,_files=[{'filename':'old.txt','previous_filename':'old.py'}]),'main',POLICY) is None
    assert metadata_filter(pr(1,_timeline=[]),'main',POLICY)=='lifecycle-terminal-unproven'


def test_timezone_same_instant_and_incomplete_file_lists():
    assert metadata_filter(pr(1,closed_at='2022-01-01T03:00:00+03:00'),'main',POLICY) is None
    assert metadata_filter(pr(1,changed_files=3001,_files_complete=False),'main',POLICY)=='file-list-exceeds-api-cap'
    assert metadata_filter(pr(1,_files=[{'filename':'readme.md'}]),'main',POLICY)=='non-python'


def test_lazy_filter_equals_eager_and_metadata_failures_do_not_consume_slots():
    items=[pr(n) for n in range(1,10)];details={v['number']:deepcopy(v) for v in items}
    details[2]['_files']=[{'filename':'README.md'}]
    policy={**POLICY,'pairs_per_repository':3};called=[]
    def load(n):called.append(n);return details[n]
    result=select_pairs(items,1,'main',policy,load)
    eager=[p for p in enumerate_pairs(items,1)[0] if all(metadata_filter(details[p[n]],'main',policy) is None for n in ('A','B'))][:3]
    assert [(p['A'],p['B']) for p in result['selected']]==[(p['A'],p['B']) for p in eager]
    assert [p['slot'] for p in result['selected']]==[1,2,3]
    assert len(called)==len(set(called)) and len(called)<len(items)
    assert [p['rank'] for p in result['ledger']]==list(range(1,len(result['ledger'])+1))
    assert result['reuse']['distinct_prs']<=6


def test_ceiling_retains_deterministic_ranked_prefix():
    def fail(n):raise Ceiling('fixture limit')
    result=select_pairs([pr(n) for n in range(1,5)],1,'main',POLICY,fail)
    assert result['stop_reason']=='request-ceiling' and result['ledger'][0]['rank']==1
    assert result['selected']==[]


def test_required_page_failure_retains_rank_but_marks_cohort_incomplete():
    from benchmarks.s17b.selection import Incomplete
    def fail(n):raise Incomplete('synthetic missing page')
    result=select_pairs([pr(n) for n in range(1,4)],1,'main',POLICY,fail)
    assert result['stop_reason']=='acquisition-incomplete' and result['ledger'][0]['rank']==1
    assert result['ledger'][0]['outcome']=='unattempted-acquisition-incomplete'


def test_unset_policy_cannot_form_checkpoint(tmp_path):
    with pytest.raises(ValueError):prepare({**POLICY,'api_version':None},tmp_path/'checkpoint.json')
    assert not (tmp_path/'checkpoint.json').exists()


def test_checkpoint_no_api_and_explicit_matching_authorization(tmp_path):
    from benchmarks.s17b.checkpoint import ROOT
    # Round 2 keeps every round-1 policy value; the synthetic checkpoint lives
    # only under tmp_path and is never used for acquisition.
    policy=json.loads((ROOT/'benchmarks/s17b/policy.json').read_text())
    from benchmarks.s17b.checkpoint import runtime_pins,READY
    policy.update(runtime_pins(),status=READY)
    checkpoint=tmp_path/'checkpoint.json';prepare(policy,checkpoint,datetime(2026,11,19,tzinfo=timezone.utc))
    approval=tmp_path/'approval.json';approval.write_text('{}')
    with pytest.raises(PermissionError):Permit(checkpoint,approval).verify()
    from benchmarks.s17b.checkpoint import sha
    approval.write_text(json.dumps({'scope':'S17b read-only acquisition','approved_by':'Polaris','checkpoint_sha256':sha(checkpoint)}))
    assert Permit(checkpoint,approval).verify()==policy
    with pytest.raises(FileExistsError):prepare(policy,checkpoint,datetime(2026,11,19,tzinfo=timezone.utc))
