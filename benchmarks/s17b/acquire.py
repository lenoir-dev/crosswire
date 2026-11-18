"""Read-only acquisition adapters; tests inject synthetic pages/receipts only."""
from dataclasses import dataclass,field
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import urlencode,urlsplit

from .checkpoint import sha
from .selection import Ceiling,RepositoryCeiling,Incomplete,timestamp,detail_filter,timeline_filter,terminal_proof,RepositoryIncomplete
from conformance.git import environment


@dataclass
class Page:
    body:object
    headers:dict=field(default_factory=dict)
    endpoint:str=''


def next_page(page):
    link=page.headers.get('link','')
    found=re.search(r'<([^>]+)>;\s*rel="next"',link)
    if not found:return None
    url=urlsplit(found[1])
    if url.scheme!='https' or url.netloc!='api.github.com':raise Incomplete('Untrusted pagination link')
    return url.path.lstrip('/')+('?' + url.query if url.query else '')


def allowed_endpoint(endpoint,policy):
    if not isinstance(endpoint,str) or '%' in endpoint or '\\' in endpoint or any(ord(c)<33 or ord(c)==127 for c in endpoint):raise ValueError('GET endpoint outside policy allowlist')
    url=urlsplit(endpoint);parts=url.path.split('/')
    if url.scheme or url.netloc or url.fragment or any(p in {'','.', '..'} or not re.fullmatch(r'[A-Za-z0-9_.-]+',p) for p in parts):raise ValueError('GET endpoint outside policy allowlist')
    if len(parts)<3 or parts[0]!='repos' or '/'.join(parts[1:3]) not in policy['repositories']:raise ValueError('GET endpoint outside policy allowlist')
    if len(parts)>3 and parts[3] not in {'pulls','issues','commits'}:raise ValueError('GET endpoint outside policy allowlist')


def endpoint_class(endpoint):
    """Pagination/query parameters do not change a request's budget class."""
    return 'commits' if re.fullmatch(r'repos/[^/]+/[^/]+/pulls/[1-9][0-9]*/commits',urlsplit(endpoint).path) else 'metadata'


class GhGet:
    """No requests until a matching checkpoint and explicit permit verify."""
    def __init__(self,permit,cache,runner=subprocess.run,version_reader=None):
        self.permit=permit;self.cache=Path(cache);self.runner=runner;self.calls=0;self.responses={};self.log=[];self.stopped=False
        self.version_reader=version_reader;self.version_checked=False

    def get(self,endpoint,**parameters):
        policy=self.permit.verify()
        allowed_endpoint(endpoint,policy)
        if not self.version_checked:
            expected=policy.get('gh_version')
            if not expected:raise ValueError('Pinned gh version required')
            actual=self.version_reader() if self.version_reader else self.runner(['gh','--version'],capture_output=True,text=True,timeout=30).stdout.splitlines()[0]
            if actual!=expected:raise ValueError('gh version differs from checkpoint')
            self.version_checked=True
        key=endpoint+('?' if '?' not in endpoint else '&')+urlencode(sorted(parameters.items())) if parameters else endpoint
        if key in self.responses:return self.responses[key]
        self.cache.mkdir(parents=True,exist_ok=True,mode=0o700)
        name=__import__('hashlib').sha256(key.encode()).hexdigest()+'.json'
        path=self.cache/name
        round_key=sha(self.permit.checkpoint) if hasattr(self.permit,'checkpoint') else 'synthetic-test-only'
        records=sorted(self.cache.glob('*.request.json'))
        if not self.log:
            self.log=[json.loads(p.read_text()) for p in records]
            if any(r.get('checkpoint_sha256')!=round_key for r in self.log):raise Incomplete('Request cache belongs to another checkpoint')
            self.calls=len(records)
        if path.exists():
            saved=json.loads(path.read_text())
            if saved.get('checkpoint_sha256')!=round_key:raise Incomplete('Cached response belongs to another checkpoint')
            page=Page(saved['body'],saved['headers'],saved['endpoint']);self.responses[key]=page
            if saved['headers'].get('retry-after') or saved['headers'].get('x-ratelimit-remaining')=='0':self.stopped=True
            for event in self.log:
                if event['endpoint']==key:event.update(status='complete',response_sha256=sha(path))
            return page
        if any(r['endpoint']==key for r in self.log):raise Incomplete('Prior GET has no durable response; do not silently retry')
        if self.stopped or self.calls>=policy['maximum_get_requests']:raise Ceiling('GET ceiling')
        if key.startswith('repos/'):
            prefix='/'.join(key.split('/')[:3])+'/'
            requests=[r for r in self.log if r['endpoint'].split('?',1)[0].rstrip('/')+'/'==prefix or r['endpoint'].startswith(prefix)]
            if len(requests)>=policy.get('per_repository_get_budget',187):raise RepositoryCeiling('Repository GET sub-budget')
            phase=endpoint_class(key)
            limit=policy.get('per_repository_'+phase+'_get_budget',60 if phase=='commits' else 127)
            if sum(endpoint_class(r['endpoint'])==phase for r in requests)>=limit:
                raise RepositoryCeiling('Repository '+phase+' GET sub-budget')
        # Cached response files are evidence, not cross-round live cache. They
        # cannot bypass the permit or silently refresh a prior snapshot.
        self.calls+=1
        event={'request':self.calls,'endpoint':key,'endpoint_class':endpoint_class(key),'status':'started','checkpoint_sha256':round_key};self.log.append(event)
        request=self.cache/f'{self.calls:06d}.request.json'
        fd=os.open(request,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as stream:
            json.dump(event,stream,sort_keys=True);stream.flush();os.fsync(stream.fileno())
        try:
            result=self.runner(['gh','api','--method','GET','--include','-H','Accept: application/vnd.github+json',
                                '-H','X-GitHub-Api-Version: '+policy['api_version'],key],capture_output=True,text=True,timeout=60)
        except (OSError,subprocess.TimeoutExpired) as error:
            event['status']='failed';raise Incomplete('GET unavailable; acquisition incomplete') from error
        if result.returncode:
            event['status']='failed';raise Incomplete('GET failed; checkpoint acquisition, do not retry outcomes')
        head,separator,body=result.stdout.replace('\r\n','\n').partition('\n\n')
        if not separator:raise Incomplete('GET response lacks headers')
        headers={}
        for line in head.splitlines()[1:]:
            if ':' in line:
                name,value=line.split(':',1);headers[name.lower()]=value.strip()
        if not head.splitlines() or not re.search(r'\s200(?:\s|$)',head.splitlines()[0]):raise Incomplete('Non-200 GET')
        try:payload=json.loads(body)
        except ValueError as error:raise Incomplete('Malformed GET body') from error
        allowed={k:v for k,v in headers.items() if k in {'date','etag','link','retry-after'} or k.startswith('x-ratelimit-')}
        page=Page(payload,allowed,key);self.responses[key]=page
        with path.open('x') as stream:
            json.dump({'endpoint':key,'headers':allowed,'body':payload,'checkpoint_sha256':round_key},stream,sort_keys=True)
            stream.flush();os.fsync(stream.fileno())
        event.update(status='complete',response_sha256=sha(path))
        if headers.get('retry-after') or headers.get('x-ratelimit-remaining')=='0':
            # Preserve the final response, but stop before making another request.
            self.stopped=True
        return page


def pages(client,endpoint,**parameters):
    result=[];ledger=[];seen=set()
    while endpoint:
        if endpoint in seen:raise Incomplete('Pagination loop')
        seen.add(endpoint);page=client.get(endpoint,**parameters);parameters={}
        if not isinstance(page.body,list):raise Incomplete('Expected paginated list')
        result.extend(page.body);ledger.append({'endpoint':page.endpoint or endpoint,'link':page.headers.get('link'), 'items':len(page.body)})
        endpoint=next_page(page)
    return result,ledger


def list_closed(client,repository,lower):
    """Only list endpoints here; exactly one additional full tail page sampled."""
    endpoint=f'repos/{repository}/pulls';parameters={'state':'closed','sort':'updated','direction':'desc','per_page':100}
    result={};ledger=[];duplicates=[];tail_remaining=0;tail_violations=0;sampled_tail=False;force_end=False
    previous=None
    while endpoint:
        page=client.get(endpoint,**parameters);parameters={}
        if not isinstance(page.body,list):raise Incomplete('PR list is not a list')
        sub_bound=False
        for pr in page.body:
            try:
                updated=timestamp(pr['updated_at'])
                end=timestamp(pr.get('merged_at') or pr['closed_at'])
            except (ValueError,KeyError,TypeError):force_end=True;updated=None;end=None
            if updated is not None:
                if previous is not None and updated>previous:force_end=True
                previous=updated
                if end is not None and updated<end:force_end=True
                if updated<timestamp(lower):
                    sub_bound=True
                    if end is not None and end>=timestamp(lower):tail_violations+=1;force_end=True
            n=pr['number']
            if n in result:
                old=result[n]
                if any(old.get(k)!=pr.get(k) for k in ('created_at','closed_at','merged_at','state')):raise Incomplete('Contradictory terminal data during pagination')
                # Equal-time edits are retained deterministically, not by page order.
                key=lambda value:(timestamp(value['updated_at']),json.dumps(value,sort_keys=True))
                kept=max((old,pr),key=key)
                duplicates.append({'number':n,'previous_updated_at':old['updated_at'],'seen_updated_at':pr['updated_at'],
                    'kept_updated_at':kept['updated_at'],'previous_sha256':__import__('hashlib').sha256(json.dumps(old,sort_keys=True).encode()).hexdigest(),
                    'seen_sha256':__import__('hashlib').sha256(json.dumps(pr,sort_keys=True).encode()).hexdigest()})
                result[n]=kept
            else:result[n]=pr
        following=next_page(page)
        ledger.append({'endpoint':page.endpoint or endpoint,'link':page.headers.get('link'),'items':len(page.body),'sub_bound':sub_bound})
        if tail_remaining:
            sampled_tail=True;tail_remaining=0
            if len(page.body)<100 and following:force_end=True
            if not force_end:break
        elif sub_bound and not force_end:
            if following:tail_remaining=1
            else:sampled_tail=True
        endpoint=following
    return {'items':list(result.values()),'pages':ledger,'total_pages':len(ledger),
            'final_link':ledger[-1]['link'] if ledger else None,'tail_sampled':sampled_tail,
            'tail_violations':tail_violations,'duplicates':duplicates,'exhausted':not following if ledger else True,
            'consistency_assumption':'unseen updated>=terminal tail is assumed, not proven',
            'coverage_hole':'currently-open reopened PRs absent; final closure after cutoff excluded'}


class Metadata:
    def __init__(self,client,repository,policy=None,default_branch=None):
        self.client=client;self.repository=repository;self.cache={};self.ledger={};self.policy=policy;self.default_branch=default_branch;self.terminal_health=[];self.health_stopped=False
    def load(self,n):
        if self.health_stopped:raise RepositoryIncomplete('Terminal-event health stop: first 10 merged PR proofs failed')
        if n in self.cache:return self.cache[n]
        prefix=f'repos/{self.repository}/pulls/{n}'
        detail=self.client.get(prefix).body
        if not isinstance(detail,dict) or detail.get('number')!=n:raise Incomplete('PR detail mismatch')
        value={**detail,'_metadata_stage':'detail','_files_complete':False,'_timeline_complete':False}
        if self.policy and detail_filter(value,self.default_branch,self.policy):self.cache[n]=value;return value
        timeline,time_pages=pages(self.client,f'repos/{self.repository}/issues/{n}/timeline',per_page=100)
        value.update(_metadata_stage='timeline',_timeline=timeline,_timeline_complete=True)
        self.ledger[n]={'timeline_pages':time_pages}
        proof=terminal_proof(value,self.policy);value['_terminal_event_proof']=proof;self.ledger[n]['terminal_event_proof']=proof
        # Fully loaded for this proof means detail plus every timeline page;
        # R2 still short-circuits before unrelated file GETs on a failed proof.
        if value.get('merged_at') and len(self.terminal_health)<10:
            self.terminal_health.append({'number':n,'reason':proof['reason']})
            if len(self.terminal_health)==10 and all(x['reason'] for x in self.terminal_health):
                self.health_stopped=True;raise RepositoryIncomplete('Terminal-event health stop: first 10 merged PR proofs failed')
        if self.policy and proof['reason']:self.cache[n]=value;return value
        files,file_pages=pages(self.client,prefix+'/files',per_page=100)
        value.update(_metadata_stage='files',_files=files,_files_complete=len(files)==detail.get('changed_files'))
        self.cache[n]=value;self.ledger[n].update(file_pages=file_pages)
        return value
    def commits(self,n,count):
        values,ledger=pages(self.client,f'repos/{self.repository}/pulls/{n}/commits',per_page=100)
        ids=[v['sha'] for v in values]
        if len(ids)!=count or len(set(ids))!=count:raise Incomplete('PR commit list incomplete')
        return ids,ledger


@dataclass(frozen=True)
class FetchReceipt:
    commit:str|None
    transferred_bytes:int|None
    error:str|None=None


class ObjectStoreTransport:
    """Authorized public fetch, accounted by Polaris's object-growth proxy.

    A fetch can exceed the remaining allowance before its final size is known;
    report the overage and stop. This is not a wire-level byte guarantee. Packs
    are already under objects and are counted once; a shrinking/unreadable store
    is unmeasurable, never recorded as a negative or zero transfer.
    """
    def __init__(self,permit,runner=subprocess.run):self.permit=permit;self.runner=runner

    @staticmethod
    def store_size(directory):
        try:
            directory=Path(directory)
            if not directory.is_dir():return None
            paths=list(directory.rglob('*'))
            if any(p.is_symlink() for p in paths):return None
            return sum(p.stat().st_size for p in paths if p.is_file())
        except OSError:return None

    def __call__(self,args,*,cwd,maximum_bytes):
        policy=self.permit.verify();cwd=Path(cwd).resolve()
        allowed=((Path('/')/'tmp').resolve(),Path(tempfile.gettempdir()).resolve())
        if not any(cwd.is_relative_to(p) for p in allowed):raise ValueError('Fetch requires disposable temporary clone')
        def local(*arguments):
            try:r=self.runner(['git',*arguments],cwd=cwd,env=environment(),capture_output=True,text=True,timeout=60)
            except (OSError,subprocess.TimeoutExpired) as error:raise Incomplete('Cannot measure disposable Git store') from error
            if r.returncode:raise Incomplete('Cannot measure disposable Git store')
            return r.stdout.strip()
        origin=local('remote','get-url','origin').removesuffix('.git').rstrip('/')
        if origin not in {'https://github.com/'+r for r in policy['repositories']}:raise ValueError('Origin outside preregistered public repositories')
        objects=Path(local('rev-parse','--git-path','objects'))
        if not objects.is_absolute():objects=cwd/objects
        if not objects.resolve().is_relative_to(cwd):raise Incomplete('External object store cannot be measured safely')
        before=self.store_size(objects)
        if before is None:raise Ceiling('Unmeasurable fetch; acquisition incomplete at ceiling')
        if maximum_bytes<=0:raise Ceiling('Git transfer ceiling')
        try:r=self.runner(['git','-c','gc.auto=0','-c','maintenance.auto=false','fetch','--progress',*args[2:]],cwd=cwd,env=environment(),capture_output=True,text=True,timeout=180)
        except (OSError,subprocess.TimeoutExpired) as error:raise Ceiling('Unmeasurable fetch; acquisition incomplete at ceiling') from error
        after=self.store_size(objects)
        if after is None or after<before:raise Ceiling('Unmeasurable fetch; acquisition incomplete at ceiling')
        # Accept only the stable C-locale progress-byte shape when present. Lack
        # of progress bytes is fine if object-store growth itself is measurable.
        reports=[]
        for amount,unit in re.findall(r'([0-9]+(?:\.[0-9]+)?)\s+(bytes|KiB|MiB|GiB)(?:\s|,)',r.stderr):
            reports.append(int(float(amount)*{'bytes':1,'KiB':1024,'MiB':1048576,'GiB':1073741824}[unit]))
        measured=max([after-before,*reports])
        if measured>maximum_bytes:return FetchReceipt(None,measured,'Git transfer ceiling')
        if r.returncode:return FetchReceipt(None,measured,'Final PR head unavailable')
        try:commit=local('rev-parse','FETCH_HEAD^{commit}')
        except Incomplete:return FetchReceipt(None,measured,'Final PR head unavailable')
        return FetchReceipt(commit,measured)


class GitBudget:
    def __init__(self,maximum=2147483648):self.maximum=maximum;self.used=0;self.stopped=False;self.head_cache={};self.receipts=[]
    @classmethod
    def from_policy(cls,permit):return cls(permit.verify()['maximum_git_bytes'])
    @property
    def remaining(self):return self.maximum-self.used
    def account(self,receipt):
        if type(receipt.transferred_bytes) is not int or receipt.transferred_bytes<0:
            self.stopped=True;raise Ceiling('Unmeasurable fetch; acquisition incomplete at ceiling')
        self.receipts.append({'commit':receipt.commit,'transferred_bytes':receipt.transferred_bytes,'error':receipt.error})
        already_stopped=self.stopped
        self.used+=receipt.transferred_bytes
        if already_stopped or self.used>self.maximum:
            self.stopped=True;raise Ceiling('Git transfer ceiling')


def fetch_head(graph,number,expected,permit,budget,transport):
    """Inject an authorized object-growth transport, or synthetic test receipt."""
    policy=permit.verify()
    if budget.maximum>policy.get('maximum_git_bytes',budget.maximum):raise ValueError('Git budget exceeds pinned policy')
    if type(number) is not int or number<1:raise ValueError('Invalid PR number')
    if budget.stopped or budget.remaining<=0:raise Ceiling('Git transfer ceiling')
    key=(str(Path(graph.repo).resolve()),number,expected)
    if key in budget.head_cache:
        saved=budget.head_cache[key]
        if saved.get('error'):raise Incomplete(saved['error'])
        return graph.commit(saved['commit'])
    try:
        receipt=transport(['git','fetch','--no-tags','origin',f'refs/pull/{number}/head'],cwd=graph.repo,maximum_bytes=budget.remaining)
    except Ceiling:
        budget.stopped=True;raise
    budget.account(receipt)
    if receipt.error:
        budget.head_cache[key]={'error':receipt.error};raise Incomplete(receipt.error)
    if receipt.commit!=expected:
        budget.head_cache[key]={'error':'Unavailable or stale final head'};raise Incomplete('Unavailable or stale final head')
    commit=graph.commit(receipt.commit);graph.bind('pr-'+str(number),commit)
    budget.head_cache[key]={'commit':commit}
    return commit


def prepare_clone(directory,repository,branch,expected,permit,budget,transport=None,runner=subprocess.run):
    """No network clone command: gated local init + metered full-history fetch.

    One cohort-wide policy-sized GitBudget must be shared with all PR fetches.
    The complete pinned branch history is fetched, without depth/filter shortcuts.
    """
    from .graph import Graph,SHA
    policy=permit.verify();directory=Path(directory).resolve()
    if repository not in policy['repositories']:raise ValueError('Repository outside policy')
    if not isinstance(expected,str) or not SHA.fullmatch(expected):raise ValueError('Invalid pinned default SHA')
    if budget.maximum>policy['maximum_git_bytes']:raise ValueError('Git budget exceeds pinned policy')
    if budget.stopped or budget.remaining<=0:raise Ceiling('Git transfer ceiling')
    if not any(directory.is_relative_to(p.resolve()) for p in (Path('/')/'tmp',Path(tempfile.gettempdir()))):raise ValueError('Clone requires disposable temporary directory')
    if any(p in {'','.', '..'} or not re.fullmatch(r'[A-Za-z0-9_.-]+',p) for p in branch.split('/')):raise ValueError('Invalid default branch')
    directory.mkdir(parents=True) # exclusive fresh directory, never an existing clone
    def local(*args):
        try:r=runner(['git',*args],cwd=directory,env=environment(),capture_output=True,timeout=60)
        except (OSError,subprocess.TimeoutExpired) as e:raise Incomplete('Disposable clone initialization failed') from e
        if r.returncode:raise Incomplete('Disposable clone initialization failed')
    local('init','--quiet')
    local('remote','add','origin','https://github.com/'+repository+'.git')
    transport=transport or ObjectStoreTransport(permit,runner)
    try:receipt=transport(['git','fetch','--no-tags','origin','refs/heads/'+branch],cwd=directory,maximum_bytes=budget.remaining)
    except Ceiling:budget.stopped=True;raise
    budget.account(receipt)
    if receipt.error:raise Incomplete(receipt.error)
    if receipt.commit!=expected:raise Incomplete('Pinned default SHA changed during acquisition')
    graph=Graph(directory,runner);commit=graph.commit(receipt.commit);graph.bind('default',commit)
    local('checkout','--quiet','-B',branch,commit)
    return graph,{'repository':repository,'default_branch':branch,'expected_default_sha':expected,
                  'fetched_default_sha':commit,'transferred_bytes':receipt.transferred_bytes,'cumulative_git_bytes':budget.used}
