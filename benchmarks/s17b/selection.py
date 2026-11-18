"""Pure list-first overlap/hash ordering and lazy metadata membership."""
from collections import Counter
from datetime import datetime,timezone
import hashlib
import re


class Incomplete(RuntimeError):pass
class Ceiling(Incomplete):pass
class RepositoryCeiling(Ceiling):pass
class RepositoryIncomplete(Incomplete):pass


def timestamp(value):
    if not isinstance(value,str):raise ValueError('missing timestamp')
    result=datetime.fromisoformat(value.replace('Z','+00:00'))
    if result.tzinfo is None:raise ValueError('timestamp lacks timezone')
    return result.astimezone(timezone.utc)


def decimal(value):
    raw=str(value)
    if isinstance(value,bool) or not re.fullmatch('[1-9][0-9]*',raw):raise ValueError('noncanonical integer')
    return raw


def pair_hash(repo_id,a,b,seed='s17b-v1'):
    parts=[decimal(repo_id),decimal(a),decimal(b)]
    if int(parts[1])>=int(parts[2]):raise ValueError('A must precede B numerically')
    return hashlib.sha256((seed+'|'+'|'.join(parts)).encode()).hexdigest()


def interval(pr):
    start=timestamp(pr.get('created_at'))
    merged=pr.get('merged_at');closed=pr.get('closed_at')
    end=timestamp(merged or closed)
    if start>=end or merged and closed and end>timestamp(closed):raise ValueError('inconsistent lifecycle')
    return start,end


def enumerate_pairs(items,repo_id,seed='s17b-v1',policy=None):
    by_number={};uncertainties=[]
    for pr in items:
        number=int(decimal(pr['number']))
        if number in by_number and by_number[number]!=pr:raise Incomplete('moving/contradictory list record')
        by_number[number]=pr
    outside=[]
    if policy:
        for n,pr in list(by_number.items()):
            try:
                # Only a proven terminal field removes a PR before ranking.
                _,end=interval(pr)
                if not timestamp(policy['terminal_lower'])<=end<timestamp(policy['collection_cutoff']):outside.append(n);del by_number[n]
            except (ValueError,TypeError):pass
    values=sorted(by_number)
    candidates=[];nonoverlap=0
    for i,a in enumerate(values):
        for b in values[i+1:]:
            unknown=False
            try:
                sa,ea=interval(by_number[a]);sb,eb=interval(by_number[b])
                if max(sa,sb)>=min(ea,eb):nonoverlap+=1;continue
            except ValueError:unknown=True;uncertainties.append([a,b])
            candidates.append({'A':a,'B':b,'hash':pair_hash(repo_id,a,b,seed),'list_uncertain':unknown})
    candidates.sort(key=lambda p:(p['hash'],p['A'],p['B']))
    for rank,pair in enumerate(candidates,1):pair['rank']=rank
    return candidates,{'pr_count':len(values),'provably_nonoverlapping_pairs':nonoverlap,'uncertain_pairs':uncertainties,'terminal_window_exclusions':sorted(outside)}


def detail_filter(pr,default_branch,policy):
    try:
        start,end=interval(pr)
        if not timestamp(policy['terminal_lower'])<=end<timestamp(policy['collection_cutoff']):return 'terminal-window'
        if pr.get('state')!='closed':return 'nonterminal-state'
        if pr.get('base',{}).get('ref')!=default_branch:return 'default-base'
        if type(pr.get('changed_files')) is not int or pr['changed_files']<1:return 'empty-or-invalid-diff'
        if pr['changed_files']>3000:return 'file-list-exceeds-api-cap'
        if pr.get('merged') is False and pr.get('merged_at'):return 'lifecycle-inconsistent'
    except (ValueError,KeyError,TypeError):return 'invalid-metadata'
    return None


def terminal_proof(pr):
    """Complete terminal timeline only; equal-time events share last position."""
    try:
        start,end=interval(pr)
        if not pr.get('_timeline_complete'):return {'reason':'incomplete-metadata'}
        events=pr['_timeline']
        if any(e.get('event') in {'reopened','base_ref_changed','base_ref_renamed'} for e in events):return {'reason':'lifecycle-or-base-changed'}
        terminal=[(e['event'],timestamp(e['created_at'])) for e in events if e.get('event') in {'closed','merged'}]
        if any(t<start for _,t in terminal):return {'reason':'lifecycle-inconsistent'}
        required='merged' if pr.get('merged_at') else 'closed'
        candidates=[t for event,t in terminal if event==required]
        if not candidates:return {'reason':'lifecycle-terminal-unproven','required_event':required}
        event=max(candidates);last=max(t for _,t in terminal);skew=(event-end).total_seconds()
        return {'reason':None if event==last and abs(skew)<=60 else 'lifecycle-terminal-unproven',
                'required_event':required,'event_at':event.isoformat(),'field_at':end.isoformat(),
                'last_terminal_at':last.isoformat(),'skew_seconds':skew,'tolerance_seconds':60}
    except (ValueError,KeyError,TypeError):return {'reason':'invalid-metadata'}


def timeline_filter(pr):return terminal_proof(pr)['reason']


def files_filter(pr):
    try:
        if not pr.get('_files_complete'):return 'incomplete-metadata'
        files=pr['_files']
        if type(pr.get('changed_files')) is not int or pr['changed_files']!=len(files):return 'incomplete-file-list'
        if len({f['filename'] for f in files})!=len(files):return 'duplicate-file-list'
        if not any(any(isinstance(f.get(k),str) and f[k].endswith('.py') for k in ('filename','previous_filename')) for f in files):return 'non-python'
    except (ValueError,KeyError,TypeError):return 'invalid-metadata'
    return None


def metadata_filter(pr,default_branch,policy):
    return detail_filter(pr,default_branch,policy) or timeline_filter(pr) or files_filter(pr)


def select_pairs(items,repo_id,default_branch,policy,load_metadata):
    ordered,counts=enumerate_pairs(items,repo_id,policy['pair_order_seed'],policy)
    cache={};selected=[];ledger=[];reason='order-exhausted'
    for candidate in ordered:
        if len(selected)>=policy['pairs_per_repository']:reason='cap';break
        outcomes={};details={}
        try:
            for label in ('A','B'):
                n=candidate[label]
                if n not in cache:cache[n]=load_metadata(n)
                details[label]=cache[n];outcomes[label]=metadata_filter(cache[n],default_branch,policy)
                if outcomes[label]:break # R2: A failure never triggers B metadata.
        except RepositoryIncomplete as error:
            ledger.append({**candidate,'metadata_outcomes':outcomes,'stage':'metadata','outcome':'unattempted-acquisition-incomplete','reason':str(error)})
            reason='repository-acquisition-incomplete';break
        except RepositoryCeiling:
            ledger.append({**candidate,'metadata_outcomes':outcomes,'stage':'metadata','outcome':'unattempted-repository-ceiling'})
            reason='repository-request-ceiling';break
        except Ceiling:
            ledger.append({**candidate,'metadata_outcomes':outcomes,'stage':'metadata','outcome':'unattempted-ceiling'})
            reason='request-ceiling';break
        except Incomplete:
            ledger.append({**candidate,'metadata_outcomes':outcomes,'stage':'metadata','outcome':'unattempted-acquisition-incomplete'})
            reason='acquisition-incomplete';break
        failure=next((v for v in outcomes.values() if v),None)
        # Recheck overlap against detail records without redefining hash order.
        if not failure:
            try:
                sa,ea=interval(details['A']);sb,eb=interval(details['B'])
                if max(sa,sb)>=min(ea,eb):failure='detail-overlap-inconsistent'
                if details['A']['base']['repo']['id']!=int(repo_id) or details['B']['base']['repo']['id']!=int(repo_id):failure='base-repository'
            except (ValueError,KeyError,TypeError):failure='invalid-metadata'
        failed_pr=next((n for n in ('A','B') if outcomes.get(n)),None)
        record={**candidate,'metadata_outcomes':outcomes,'stage':'metadata','outcome':failure or 'selected',
                'first_failed_pr':failed_pr,'first_failed_filter':failure,
                'first_failed_stage':details.get(failed_pr,{}).get('_metadata_stage') if failed_pr else None}
        if not failure:
            record['slot']=len(selected)+1
            selected.append({**candidate,'slot':record['slot'],'details':details})
        ledger.append(record)
    reuse=Counter(n for p in selected for n in (p['A'],p['B']))
    return {'selected':selected,'ledger':ledger,'list_counts':counts,'stop_reason':reason,
            'ranked_pairs':len(ordered),'unattempted_pairs':len(ordered)-len(ledger),
            'reuse':{'distinct_prs':len(reuse),'maximum_pairs_per_pr':max(reuse.values(),default=0),'per_pr':dict(reuse)}}
