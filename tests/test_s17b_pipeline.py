"""Post-metadata exclusion ordering; injected pure evidence, never acquisition."""
from types import SimpleNamespace

from benchmarks.s17b import pipeline
from benchmarks.s17b.graph import Anchor


def fixture(monkeypatch,contaminated=False):
    order=[]
    monkeypatch.setattr(pipeline,'fetch_head',lambda graph,n,expected,*a:(order.append('fetch-'+str(n)) or expected))
    monkeypatch.setattr(pipeline,'anchor',lambda *a:(order.append('anchor') or Anchor('squash-n1','c'*40,'d'*40,1,'single')))
    monkeypatch.setattr(pipeline,'own_bases',lambda *a:(order.append('bases') or {'A':'d'*40,'B':'d'*40,'L':'d'*40}))
    monkeypatch.setattr(pipeline,'contamination',lambda *a:(order.append('contamination') or {'reason':'contaminated-heads' if contaminated else None}))
    monkeypatch.setattr(pipeline,'integrate_pair',lambda *a:(order.append('integrate') or {'I_AB':'f'*40}))
    graph=SimpleNamespace(parents=lambda c:['d'*40])
    metadata=SimpleNamespace(commits=lambda n,count:([str(n)*40],[]))
    permit=SimpleNamespace(verify=lambda:{})
    slot={'rank':7,'hash':'a'*64,'slot':2,'A':1,'B':2,'details':{
      'A':{'created_at':'2025-01-01T00:00:00Z','closed_at':'2025-02-01T00:00:00Z','head':{'sha':'1'*40},'commits':1},
      'B':{'created_at':'2025-01-01T00:00:00Z','closed_at':'2025-03-01T00:00:00Z','head':{'sha':'2'*40},'commits':1}}}
    return order,slot,graph,metadata,permit


def test_post_metadata_exclusion_retains_slot_and_precedes_integration(monkeypatch):
    order,slot,graph,metadata,permit=fixture(monkeypatch,True)
    result=pipeline.prepare_pair(slot,graph,'default',metadata,permit,None,None,integrate=True)
    assert result['slot']==2 and result['rank']==7 and result['reason']=='contaminated-heads'
    assert result['anchor_method']=='squash-n1' and 'integrate' not in order


def test_all_graph_checks_precede_virtual_integration(monkeypatch):
    order,slot,graph,metadata,permit=fixture(monkeypatch)
    result=pipeline.prepare_pair(slot,graph,'default',metadata,permit,None,None,integrate=True)
    assert result['status']=='ready' and order==['fetch-1','fetch-2','anchor','bases','contamination','integrate']
    assert result['states']['I_AB']=='f'*40


def test_ceiling_marks_remaining_slots_without_more_acquisition(monkeypatch):
    from benchmarks.s17b.acquire import GitBudget
    from benchmarks.s17b.selection import Ceiling
    order,slot,graph,metadata,permit=fixture(monkeypatch)
    budget=GitBudget();calls=[]
    def fail(*a,**kw):calls.append(1);budget.stopped=True;raise Ceiling('synthetic')
    monkeypatch.setattr(pipeline,'fetch_head',fail)
    results=pipeline.prepare_slots([slot,{**slot,'slot':3}],graph,'default',metadata,permit,budget,None)
    assert len(calls)==1 and [r['slot'] for r in results]==[2,3]
    assert all(r['status']=='unattempted' for r in results)


def test_terminal_tie_merged_pr_is_earlier_and_anchor_counts_reported(monkeypatch):
    order,slot,graph,metadata,permit=fixture(monkeypatch)
    slot['details']['B']['closed_at']=slot['details']['A']['closed_at']
    slot['details']['A']['merged_at']=slot['details']['A']['closed_at']
    result=pipeline.prepare_pair(slot,graph,'default',metadata,permit,None,None)
    assert result['earlier']=='A' and result['status']=='ready'
    assert pipeline.graph_summary([result])['anchor_method']=={'squash-n1':1}
