"""Thin acquisition wiring only; no checker, detector, labels or checkpoint 2.

A fresh temporary root owns one round. Existing evidence is never overwritten or
silently resumed. All network runners/transports are injected in synthetic tests.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile

from .acquire import GhGet,Metadata,ObjectStoreTransport,GitBudget,prepare_clone
from .collect import collect_metadata
from .pipeline import prepare_slots,graph_summary
from .selection import Ceiling,Incomplete
from .graph import Unresolved


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
    root.mkdir(parents=True,mode=0o700) # existing rounds must not replay API/fetch
    write_record(root/'started.json',{'stage':'acquisition only; no labels or measurement',
                                   'policy':policy,'authorization':'Permit verified; procedural, not signed'})
    client=GhGet(permit,root/'requests',runner=runner)
    budget=GitBudget.from_policy(permit) # ONE instance for default and all heads.
    transport=transport if transport is not None else ObjectStoreTransport(permit,runner=runner)
    metadata=collect_metadata(client,policy)
    write_record(root/'metadata.json',metadata) # selection durable BEFORE any Git fetch
    rows=[]
    for index,repository in enumerate(metadata['repositories']):
        row={'repository':repository['repository'],'stage':'acquisition','status':'unattempted'}
        slots=repository.get('selection',{}).get('selected',[])
        if not slots:
            row['reason']=repository.get('reason') or repository.get('selection',{}).get('stop_reason','no-selected-slots')
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
            except (Ceiling,Incomplete,Unresolved) as error:
                row.update(status='acquisition-incomplete',reason=str(error).replace(str(root),'${ACQUISITION}'))
                row['slots']=[{k:slot[k] for k in ('A','B','rank','hash','slot')} |
                              {'status':'unattempted','reason':row['reason'],'anchor_method':'unresolved'} for slot in slots]
        rows.append(row)
        write_record(root/f'repository-{index+1:02d}.json',row)
    complete=(metadata['complete'] and all(row['status']=='graph-acquired' or
              not repository.get('selection',{}).get('selected') for row,repository in zip(rows,metadata['repositories'])))
    complete=complete and not any(slot['status']=='unattempted' for row in rows for slot in row.get('slots',[]))
    result={'stage':'acquisition only; no checker/detector/labels/checkpoint-2','status':'acquired' if complete else 'acquisition-incomplete',
            'metadata_complete':metadata['complete'],'repositories':rows,'get_requests':client.calls,
            'request_ledger':client.log,'git_bytes':budget.used,'git_ceiling':budget.maximum,'git_stopped':budget.stopped,
            'fetch_receipts':budget.receipts}
    write_record(root/'acquisition.json',result)
    return result
