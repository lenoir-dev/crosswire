"""Post-metadata slots never get replaced. All calls require injected evidence."""
from dataclasses import asdict
from collections import Counter

from benchmarks.s17.m3 import delta,label,minimal_attribution
from .selection import interval,Incomplete,Ceiling
from .graph import anchor,own_bases,contamination,integrate_pair,Unresolved,pre_update_head
from .acquire import fetch_head


def prepare_pair(slot,graph,default_head,metadata,permit,budget,transport,*,integrate=False):
    result={'rank':slot['rank'],'hash':slot['hash'],'slot':slot['slot'],'A':slot['A'],'B':slot['B'],
            'head_kind':'final-head','stage':'post-metadata','anchor_method':'unresolved','status':'unlabelled','reason':None}
    try:
        policy=permit.verify();details=slot['details'];heads={};commits={}
        for name in ('A','B'):
            pr=details[name]
            heads[name]=fetch_head(graph,slot[name],pr['head']['sha'],permit,budget,transport)
            commits[name],_=metadata.commits(slot[name],pr['commits'])
        ends={name:interval(pr)[1] for name,pr in details.items()}
        earlier='A' if ends['A']<ends['B'] else 'B'
        if ends['A']==ends['B']:
            merged=[n for n in ('A','B') if details[n].get('merged_at')]
            if len(merged)==1:earlier=merged[0]
            elif len(merged)==2:
                chain=graph.chain(default_head)
                cs=[details[n].get('merge_commit_sha') for n in ('A','B')]
                if cs[0]==cs[1] or any(c not in chain for c in cs):raise Unresolved('terminal-tie-anchor-unresolved')
                earlier='A' if chain.index(cs[0])>chain.index(cs[1]) else 'B'
            else:raise Unresolved('terminal-tie-anchor-unresolved')
        anchored=anchor(graph,details[earlier],default_head,commits[earlier])
        result.update(anchor=asdict(anchored),anchor_method=anchored.method,earlier=earlier,heads=heads)
        if anchored.method=='unresolved':raise Unresolved(anchored.reason or 'default-anchor-unresolved')
        bases=own_bases(graph,anchored.D,heads['A'],heads['B']);result['bases']=bases
        proof=contamination(graph,heads['A'],heads['B'],anchored.D,anchored.C,earlier,bases)
        result['contamination']=proof
        if (proof.get('test')=='integrated-earlier-pr' and
            policy.get('apparatus',{}).get('pre_update_heads',{}).get('enabled')):
            other='B' if earlier=='A' else 'A'
            result['final_heads']=dict(heads);result['final_contamination']=proof
            try:
                adjustment=pre_update_head(graph,heads['A'],heads['B'],anchored.D,anchored.C,earlier,default_head,commits[other])
            except Unresolved as error:
                result['pre_update_rejection']=str(error)
                raise Unresolved(proof['reason']) from error
            heads=adjustment['heads'];bases=adjustment['bases'];proof=adjustment['contamination']
            graph.bind('pre-update-pr-'+str(slot[other]),heads[other])
            result.update(head_kind='pre-update',heads=heads,bases=bases,contamination=proof,head_adjustment=adjustment)
        if proof['reason']:raise Unresolved(proof['reason'])
        result.update(status='ready',stage='graph-proven')
        if integrate:
            result['states']=integrate_pair(graph,bases['L'],heads['A'],heads['B'],'pair-'+str(slot['A'])+'-'+str(slot['B']))
            result['stage']='virtual-integration'
    except Ceiling:
        result.update(status='unattempted',reason='ceiling')
    except (Incomplete,Unresolved,KeyError,ValueError,TypeError) as error:
        result.update(status='unlabelled',reason=str(error))
    return result


def m3_contract(observations,path_maps):
    """Synthetic-tested adapter; not an entry point that executes any oracle.

    Caller supplies already observed B_A/H_A/B_B/H_B/L/A_L/B_L/I_AB. Attribution
    uses I_AB only; I_BA is for graph/tree-order equivalence, not a second label.
    """
    for name in ('A','B'):
        change=delta(observations['B_'+name],observations['H_'+name],path_maps.get('own_'+name))
        if change.status!='complete' or change.new:
            return {'eligible':False,'label':'unlabelled','reason':'own-base-'+(change.reason or 'new-tip-diagnostic'),'diagnostics':()}
    answer=label(observations['L'],{'A':observations['A_L'],'B':observations['B_L']},observations['I_AB'],path_maps.get('common'))
    if answer['eligible'] and answer['diagnostics']:
        states={frozenset():observations['L'],frozenset({'A'}):observations['A_L'],frozenset({'B'}):observations['B_L'],frozenset({'A','B'}):observations['I_AB']}
        if any(minimal_attribution(observations['L'],states,{'A','B'},d,path_maps.get('minimal')) is not True for d in answer['diagnostics']):
            return {'eligible':False,'label':'unlabelled','reason':'attribution-uncertain','diagnostics':()}
    return answer


def prepare_slots(slots,graph,default_head,metadata,permit,budget,transport,*,integrate=False):
    """Preserve selected slots after ceiling; never replace failed acquisitions."""
    results=[];stopped=False
    for slot in slots:
        if budget.stopped or stopped:
            results.append({k:slot[k] for k in ('A','B','rank','slot','hash')} |
                           {'status':'unattempted','reason':'ceiling','anchor_method':'unresolved','head_kind':'final-head','stage':'post-metadata'})
        else:
            results.append(prepare_pair(slot,graph,default_head,metadata,permit,budget,transport,integrate=integrate))
            if results[-1].get('reason')=='ceiling':stopped=True
    return results


def graph_summary(results):
    """Per-repository report cell; unattempted slots are not anchor attempts."""
    attempted=[r for r in results if r['status']!='unattempted']
    return {'head_kind':{kind:{'pairs':sum(r.get('head_kind','final-head')==kind for r in results),
            'ready':sum(r.get('head_kind','final-head')==kind and r['status']=='ready' for r in results)}
            for kind in ('final-head','pre-update')},'anchor_method':dict(Counter(r['anchor_method'] for r in attempted)),
            'anchor_exclusions':sum(r['anchor_method']=='unresolved' for r in attempted),
            'contamination_exclusions':sum(str(r.get('reason') or '').startswith('contaminat') for r in attempted),
            'unattempted':len(results)-len(attempted)}
