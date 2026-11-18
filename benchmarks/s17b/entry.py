"""Thin acquisition wiring only; no checker, detector, labels or checkpoint 2.

A temporary root owns one round. P7 resumes replay its immutable response cache
and retain each acquisition attempt. All transports are injected in tests.
"""
import json
import fcntl
import time
import traceback
import os
from pathlib import Path
import subprocess
import tempfile

from .acquire import GhGet,Metadata,ObjectStoreTransport,GitBudget,prepare_clone
from .collect import collect_metadata
from .pipeline import prepare_slots,graph_summary
from .selection import Ceiling,Incomplete
from .graph import Unresolved
from .reporting import repository_report
from .journal import write,selection_policy
from .resume import FetchJournal
from .http import sanitize
from .checkpoint import sha


def write_record(path,value):
    """Durable exclusive evidence; retain all earlier records on any failure."""
    data=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode()
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as stream:
        stream.write(data);stream.flush();os.fsync(stream.fileno())
    directory=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(directory)
    finally:os.close(directory)


def acquire(permit,root,*,runner=subprocess.run,transport=None):
    policy=permit.verify() # BEFORE creating files, checking gh or any transport.
    root=Path(root).resolve()
    if not any(root.is_relative_to(p.resolve()) for p in (Path('/')/'tmp',Path(tempfile.gettempdir()))):
        raise ValueError('Acquisition requires a fresh disposable temporary root')
    enabled=policy.get('apparatus',{}).get('resume',{}).get('enabled',False)
    root.mkdir(parents=True,mode=0o700,exist_ok=enabled)
    with (root/'.controller.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        legacy=(root/'started.json').exists() and not (root/'attempts').exists()
        if (root/'started.json').exists():
            prior=json.loads((root/'started.json').read_text())
            if selection_policy(prior['policy'])!=selection_policy(policy):raise ValueError('Root selection policy drift')
        else:write_record(root/'started.json',{'stage':'acquisition only; no labels or measurement','policy':policy,'authorization':'Permit verified; procedural, not signed'})
        attempts=root/'attempts';attempts.mkdir(exist_ok=True)
        number=max([int(path.name.split('.')[0]) for path in attempts.glob('*.started.json')],default=1 if legacy else 0)+1
        checkpoint=sha(permit.checkpoint) if hasattr(permit,'checkpoint') else 'synthetic-test-only'
        write_record(attempts/f'{number:06d}.started.json',{'attempt':number,'checkpoint_sha256':checkpoint,'started_at':time.time(),'resume':number>1 or (root/'requests').exists(),'legacy_predecessor_started_sha256':sha(root/'started.json') if legacy else None})
        try:
            result=_acquire(permit,policy,root,number,runner,transport)
        except BaseException as error:
            write_record(attempts/f'{number:06d}.result.json',{'status':'interrupted','exception_class':type(error).__name__,'traceback':sanitize(traceback.format_exc(),root),'finished_at':time.time()})
            raise
        write_record(attempts/f'{number:06d}.result.json',{'status':result['status'],'finished_at':time.time()})
        return result


def _acquire(permit,policy,root,attempt,runner,transport):
    client=GhGet(permit,root/'requests',runner=runner)
    checkpoint=sha(permit.checkpoint) if hasattr(permit,'checkpoint') else 'synthetic-test-only'
    client._restore(policy,checkpoint) # cached budgets/lineage before any runner
    budget=GitBudget.from_policy(permit)
    transport=transport if transport is not None else ObjectStoreTransport(permit,runner=runner)
    if policy.get('apparatus',{}).get('resume',{}).get('enabled'):
        transport=FetchJournal(root,transport,budget,checkpoint,client.approved_checkpoints)
    def snapshot(value):
        write(root/'attempts'/f'{attempt:06d}.metadata-{len(value["repositories"]):02d}.json',value)
    metadata=collect_metadata(client,policy,metadata_path=root/'metadata.json',on_repository=snapshot)
    rows=[]
    for index,repository in enumerate(metadata['repositories']):
        client.active_repository=repository['repository']
        row={'repository':repository['repository'],'stage':'acquisition','status':'unattempted'}
        slots=repository.get('selection',{}).get('selected',[])
        prior_path=root/f'repository-{index+1:02d}.json'
        prior=json.loads(prior_path.read_text()) if prior_path.exists() else None
        if prior and prior.get('status')=='graph-acquired' and all(slot['status']!='unattempted' for slot in prior.get('slots',[])):
            expected=[{k:s[k] for k in ('A','B','rank','hash','slot')} for s in slots]
            observed=[{k:s[k] for k in ('A','B','rank','hash','slot')} for s in prior.get('slots',[])]
            if observed!=expected:raise ValueError('Cached graph selection drift')
            row=prior
        elif not slots:
            row['reason']=repository.get('reason') or repository.get('selection',{}).get('stop_reason','no-selected-slots')
        elif (policy.get('apparatus',{}).get('pr_isolation',{}).get('enabled') and
              len(getattr(client,'pr_failures',{}).get(repository['repository'],{}))>=policy['apparatus']['pr_isolation']['maximum_failed_prs_per_repository']):
            row['reason']='repository-pr-failure-health-stop'
            row['slots']=[{k:slot[k] for k in ('A','B','rank','hash','slot')} |
                          {'status':'unattempted','reason':row['reason'],'anchor_method':'unresolved'} for slot in slots]
        elif budget.stopped or budget.remaining<=0 or client.stopped or client.calls>=policy['maximum_get_requests']:
            row['reason']='acquisition-incomplete-at-ceiling'
            row['slots']=[{k:slot[k] for k in ('A','B','rank','hash','slot')} |
                          {'status':'unattempted','reason':'ceiling','anchor_method':'unresolved'} for slot in slots]
        else:
            try:
                graph,receipt=prepare_clone(root/'clones'/repository['repository'],repository['repository'],
                    repository['default_branch'],repository['default_sha'],permit,budget,transport=transport,runner=runner)
                row['default_fetch']=receipt
                details=Metadata(client,repository['repository'],policy,repository['default_branch'])
                row['slots']=prepare_slots(slots,graph,repository['default_sha'],details,permit,budget,transport,integrate=False)
                row.update(status='graph-acquired',summary=graph_summary(row['slots']))
            except Exception as error:
                row.update(status='acquisition-incomplete',reason=sanitize(str(error),root),exception_class=type(error).__name__,traceback=sanitize(traceback.format_exc(),root))
                row['slots']=[{k:slot[k] for k in ('A','B','rank','hash','slot')} |
                              {'status':'unattempted','reason':row['reason'],'anchor_method':'unresolved'} for slot in slots]
        row['apparatus_report']=repository_report(client,repository['repository'],row.get('slots',[]))
        rows.append(row)
        write(root/'attempts'/f'{attempt:06d}.repository-{index+1:02d}.json',row)
        write(root/f'repository-{index+1:02d}.json',row,replace=True)
    complete=(metadata['complete'] and all(row['status']=='graph-acquired' or
              not repository.get('selection',{}).get('selected') for row,repository in zip(rows,metadata['repositories'])))
    complete=complete and not any(slot['status']=='unattempted' for row in rows for slot in row.get('slots',[]))
    result={'stage':'acquisition only; no checker/detector/labels/checkpoint-2','status':getattr(client,'stop_reason',None) or ('acquired' if complete else 'acquisition-incomplete'),
            'metadata_complete':metadata['complete'],'repositories':rows,'get_requests':client.calls,
            'request_ledger':client.log,'git_bytes':budget.used,'git_ceiling':budget.maximum,'git_stopped':budget.stopped,
            'fetch_receipts':budget.receipts,'wait_budget_used_seconds':getattr(client,'wait_budget_used',0),
            'wait_completed_seconds':getattr(client,'total_wait_seconds',0),
            'apparatus_report':{r['repository']:r['apparatus_report'] for r in rows}}
    write(root/'attempts'/f'{attempt:06d}.acquisition.json',result)
    write(root/'acquisition.json',result,replace=True)
    return result
