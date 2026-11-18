"""Bounded metadata orchestration; no Git, oracle or detector observations."""
from pathlib import Path
import traceback

from .acquire import Metadata,list_closed
from .selection import select_pairs,Incomplete,Ceiling,RepositoryCeiling
from .http import sanitize
from .journal import write


def collect_metadata(client,policy,*,metadata_path=None,on_repository=None):
    rows=[];total=0;stopped=False
    isolated=policy.get('apparatus',{}).get('repository_isolation',False)
    def snapshot():
        return {'stratum':'natural branches, virtual integration','stage':'metadata only; no graph/label attempted',
            'selected_pairs':total,'repositories':rows,
            'complete':len(rows)==len(policy['repositories']) and not stopped and not any(
                r.get('reason')=='repository-request-ceiling' or r.get('selection',{}).get('stop_reason') in
                {'repository-request-ceiling','repository-acquisition-incomplete','acquisition-incomplete'} or
                r.get('status')=='acquisition-incomplete' for r in rows),
            'get_requests':client.calls,'request_ledger':client.log,'global_stop_reason':getattr(client,'stop_reason',None)}
    def persist():
        if metadata_path:write(metadata_path,snapshot(),replace=True)
        if on_repository:on_repository(snapshot())
    persist()
    for repository in policy['repositories']:
        client.active_repository=repository
        exceptions=[]
        if stopped:
            rows.append({'repository':repository,'status':'unattempted','reason':'acquisition-incomplete-at-ceiling'});persist();continue
        try:
            detail=client.get('repos/'+repository).body
            if detail.get('private') is not False:raise Incomplete('Public repository not verified')
            repo_id=detail['id'];branch=detail['default_branch']
            default=client.get('repos/'+repository+'/commits/'+branch).body['sha']
            listing=list_closed(client,repository,policy['terminal_lower'])
            metadata=Metadata(client,repository,policy,branch)
            def load(number):
                try:return metadata.load(number)
                except Exception as error:
                    exceptions.append({'exception_class':type(error).__name__,'traceback':sanitize(traceback.format_exc(),getattr(client,'cache',Path.cwd()))})
                    raise
            selected=select_pairs(listing['items'],repo_id,branch,policy,load)
            total+=len(selected['selected'])
            if total>policy['maximum_pairs']:raise Ceiling('Global pair cap exceeded')
            rows.append({'repository':repository,'repository_id':repo_id,'default_branch':branch,'default_sha':default,
                'status':'acquisition-incomplete' if selected['stop_reason']=='repository-acquisition-incomplete' or isolated and selected['stop_reason']=='acquisition-incomplete' else 'metadata-only',
                'list':listing,'selection':selected,'metadata_pages':metadata.ledger,'pr_failures':metadata.failures,
                'terminal_health':metadata.terminal_health,'exceptions':exceptions,
                'acquisition_complete':selected['stop_reason'] not in {'repository-acquisition-incomplete','acquisition-incomplete','repository-request-ceiling','request-ceiling'}})
            if selected['stop_reason']=='request-ceiling':stopped=True
        except RepositoryCeiling as error:
            rows.append({'repository':repository,'status':'incomplete','reason':'repository-request-ceiling','exception_class':type(error).__name__})
        except Ceiling as error:
            rows.append({'repository':repository,'status':'incomplete','reason':str(error),'exception_class':type(error).__name__});stopped=True
        except Exception as error:
            rows.append({'repository':repository,'status':'acquisition-incomplete',
                'reason':sanitize(str(error),getattr(client,'cache',Path.cwd())),
                'exception_class':type(error).__name__,'traceback':sanitize(traceback.format_exc(),getattr(client,'cache',Path.cwd()))})
        persist()
    return snapshot()
