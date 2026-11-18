"""Bounded metadata orchestration for an injected authorized read-only client.

No function is called at import; the package CLI has no collection command.
This phase never invokes Git, any oracle, the detector or mutation machinery.
"""
from urllib.parse import quote
from .acquire import Metadata,list_closed
from .selection import select_pairs,Incomplete,Ceiling,RepositoryCeiling


def collect_metadata(client,policy):
    rows=[];total=0;stopped=False
    for repository in policy['repositories']:
        if stopped:
            rows.append({'repository':repository,'status':'unattempted','reason':'acquisition-incomplete-at-ceiling'});continue
        try:
            detail=client.get('repos/'+repository).body
            if detail.get('private') is not False:raise Incomplete('Public repository not verified')
            repo_id=detail['id'];branch=detail['default_branch']
            default=client.get('repos/'+repository+'/commits/'+quote(branch,safe='')).body['sha']
            listing=list_closed(client,repository,policy['terminal_lower'])
            metadata=Metadata(client,repository,policy,branch)
            selected=select_pairs(listing['items'],repo_id,branch,policy,metadata.load)
            total+=len(selected['selected'])
            if total>policy['maximum_pairs']:raise ValueError('Global pair cap exceeded')
            rows.append({'repository':repository,'repository_id':repo_id,'default_branch':branch,'default_sha':default,
                         'status':'metadata-only','list':listing,'selection':selected,'metadata_pages':metadata.ledger})
            if selected['stop_reason'] in {'request-ceiling','acquisition-incomplete'}:stopped=True
        except RepositoryCeiling:
            rows.append({'repository':repository,'status':'incomplete','reason':'repository-request-ceiling'})
            continue # R1: other repositories keep their own non-rolling budget.
        except (Ceiling,Incomplete) as error:
            rows.append({'repository':repository,'status':'incomplete','reason':str(error)})
            stopped=True
    return {'stratum':'natural branches, virtual integration','stage':'metadata only; no graph/label attempted',
            'selected_pairs':total,'repositories':rows,'complete':not stopped and not any(r.get('reason')=='repository-request-ceiling' or r.get('selection',{}).get('stop_reason')=='repository-request-ceiling' for r in rows),
            'get_requests':client.calls,'request_ledger':client.log}
