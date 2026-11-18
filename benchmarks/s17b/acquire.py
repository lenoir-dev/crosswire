"""Read-only acquisition adapters; tests inject synthetic pages/receipts only."""
from dataclasses import dataclass,field
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from urllib.parse import urlencode,urlsplit

from .checkpoint import sha
from .selection import Ceiling,RepositoryCeiling,Incomplete,timestamp,detail_filter,timeline_filter,terminal_proof,RepositoryIncomplete
from conformance.git import environment
from .http import RateLimited,sanitize,parse_reply,rate_response,server_wait,connection_failure,PRMetadataUnavailable,pr_scoped


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
    """Permit-gated GETs, bounded transport attempts, durable per-attempt results."""
    def __init__(self,permit,cache,runner=subprocess.run,version_reader=None,wait=time.sleep,clock=time.time):
        self.permit=permit;self.cache=Path(cache);self.runner=runner;self.calls=0;self.responses={};self.log=[];self.stopped=False
        self.version_reader=version_reader;self.version_checked=False;self.wait=wait;self.clock=clock;self.stop_reason=None;self.wait_budget_used=0;self.total_wait_seconds=0;self.wait_events=[]

    def _write(self,path,value):
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as stream:
            json.dump(value,stream,sort_keys=True);stream.flush();os.fsync(stream.fileno())
        directory=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(directory)
        finally:os.close(directory)

    def _budget(self,policy,key):
        if self.stopped:
            if self.stop_reason=='acquisition-incomplete-rate-limited':raise RateLimited()
            raise Ceiling('GET ceiling')
        if self.calls>=policy['maximum_get_requests']:raise Ceiling('GET ceiling')
        prefix='/'.join(urlsplit(key).path.split('/')[:3])+'/'
        requests=[r for r in self.log if urlsplit(r['endpoint']).path.rstrip('/')+'/'==prefix or urlsplit(r['endpoint']).path.startswith(prefix)]
        if len(requests)>=policy.get('per_repository_get_budget',187):raise RepositoryCeiling('Repository GET sub-budget')
        phase=endpoint_class(key);limit=policy.get('per_repository_'+phase+'_get_budget',60 if phase=='commits' else 127)
        if sum(endpoint_class(r['endpoint'])==phase for r in requests)>=limit:raise RepositoryCeiling('Repository '+phase+' GET sub-budget')

    def _pause(self,seconds):
        if seconds<=0:return
        limit=self.permit.verify().get('apparatus',{}).get('transport',{}).get('maximum_total_wait_seconds',900)
        event=self.log[-1]
        wait={'request':event['request'],'endpoint':event['endpoint'],'checkpoint_sha256':event['checkpoint_sha256'],
              'planned_seconds':seconds,'waited_seconds':0,'status':'started'}
        if self.wait_budget_used+seconds>limit:
            self.stopped=True;self.stop_reason='acquisition-incomplete-rate-limited'
            self._write(self.cache/'cohort-stop.json',{**wait,'status':self.stop_reason,'reason':'total-wait-ceiling',
                                                    'wait_budget_used':self.wait_budget_used,'limit_seconds':limit})
            self.wait_events.append({**wait,'status':'blocked-total-wait-ceiling'})
            raise RateLimited()
        self.wait_budget_used+=seconds
        self._write(self.cache/f'{event["request"]:06d}.wait-started.json',wait)
        self.wait_events.append(wait)
        while seconds>0:
            step=min(60,seconds);self.wait(step);seconds-=step
            wait['waited_seconds']+=step;self.total_wait_seconds+=step
        wait['status']='complete'
        self._write(self.cache/f'{event["request"]:06d}.wait-result.json',wait)

    def _finish(self,event,**fields):
        event.update(fields)
        self._write(self.cache/f'{event["request"]:06d}.result.json',event)

    def get(self,endpoint,**parameters):
        policy=self.permit.verify();allowed_endpoint(endpoint,policy)
        if not self.version_checked:
            expected=policy.get('gh_version')
            if not expected:raise ValueError('Pinned gh version required')
            actual=self.version_reader() if self.version_reader else self.runner(['gh','--version'],capture_output=True,text=True,timeout=30).stdout.splitlines()[0]
            if actual!=expected:raise ValueError('gh version differs from checkpoint')
            self.version_checked=True
        key=endpoint+('?' if '?' not in endpoint else '&')+urlencode(sorted(parameters.items())) if parameters else endpoint
        if key in self.responses:return self.responses[key]
        self.cache.mkdir(parents=True,exist_ok=True,mode=0o700)
        path=self.cache/(__import__('hashlib').sha256(key.encode()).hexdigest()+'.json')
        round_key=sha(self.permit.checkpoint) if hasattr(self.permit,'checkpoint') else 'synthetic-test-only'
        if not self.log:
            for record in sorted(self.cache.glob('*.request.json')):
                item=json.loads(record.read_text());result=record.with_name(record.name.replace('.request.json','.result.json'))
                if result.exists():item=json.loads(result.read_text())
                if item.get('checkpoint_sha256')!=round_key:raise Incomplete('Request cache belongs to another checkpoint')
                self.log.append(item)
                if item.get('outcome')=='acquisition-incomplete-rate-limited' or item.get('global_stop_reason')=='acquisition-incomplete-rate-limited':
                    self.stopped=True;self.stop_reason='acquisition-incomplete-rate-limited'
            self.calls=len(self.log)
            for started in sorted(self.cache.glob('*.wait-started.json')):
                value=json.loads(started.read_text())
                if value['checkpoint_sha256']!=round_key:raise Incomplete('Wait journal belongs to another checkpoint')
                self.wait_budget_used+=value['planned_seconds']
                result=started.with_name(started.name.replace('.wait-started.json','.wait-result.json'))
                if result.exists():
                    value=json.loads(result.read_text());self.total_wait_seconds+=value['waited_seconds']
                else:value.update(status='unconfirmed',waited_seconds=0)
                self.wait_events.append(value)
            if (self.cache/'cohort-stop.json').exists():
                value=json.loads((self.cache/'cohort-stop.json').read_text())
                if value['checkpoint_sha256']!=round_key:raise Incomplete('Stop journal belongs to another checkpoint')
                self.stopped=True;self.stop_reason='acquisition-incomplete-rate-limited'
        if path.exists():
            saved=json.loads(path.read_text())
            if saved.get('checkpoint_sha256')!=round_key:raise Incomplete('Cached response belongs to another checkpoint')
            page=Page(saved['body'],saved['headers'],saved['endpoint']);self.responses[key]=page
            return page
        if any(r['endpoint']==key for r in self.log):raise Incomplete('Prior GET has no durable response; do not silently retry')
        settings=policy.get('apparatus',{}).get('transport',{})
        maximum=settings.get('max_attempts',1)
        if type(maximum) is not int or not 1<=maximum<=3:raise ValueError('Transport attempt cap must be 1..3')
        for attempt in range(1,maximum+1):
            policy=self.permit.verify();self._budget(policy,key)
            self.calls+=1
            event={'request':self.calls,'endpoint':key,'endpoint_class':endpoint_class(key),'operation_attempt':attempt,
                   'status':'started','checkpoint_sha256':round_key,'started_at':self.clock()}
            self.log.append(event);self._write(self.cache/f'{self.calls:06d}.request.json',event)
            error=None;result=None
            try:
                result=self.runner(['gh','api','--method','GET','--include','-H','Accept: application/vnd.github+json',
                    '-H','X-GitHub-Api-Version: '+policy['api_version'],key],capture_output=True,text=True,timeout=settings.get('pr_timeout_seconds',120) if pr_scoped(key) else settings.get('timeout_seconds',60))
            except (OSError,subprocess.TimeoutExpired) as failure:error=failure
            stdout=result.stdout if result else ''
            stderr=getattr(result,'stderr','') if result else getattr(error,'stderr',None) or str(error)
            status,headers,body=parse_reply(stdout,stderr)
            fields={'exit_status':result.returncode if result else None,'http_status':status,
                    'exception':type(error).__name__ if error else None,'stderr':sanitize(stderr,self.cache),'finished_at':self.clock(),
                    'headers':{k:v for k,v in headers.items() if k in {'date','etag','link','retry-after'} or k.startswith('x-ratelimit-')}}
            rate=rate_response(status,headers)
            required_wait=server_wait(headers,self.clock()) if rate else None
            if rate and (required_wait is None or required_wait>settings.get('maximum_rate_wait_seconds',300)):
                self.stopped=True;self.stop_reason='acquisition-incomplete-rate-limited'
                self._finish(event,**fields,status='failed',outcome=self.stop_reason,required_wait_seconds=required_wait)
                raise RateLimited()
            if result and result.returncode==0 and status==200 and body is not None:
                try:payload=json.loads(body)
                except ValueError:
                    self._finish(event,**fields,status='failed',outcome='malformed-body')
                    raise Incomplete('Malformed GET body')
                allowed={k:v for k,v in headers.items() if k in {'date','etag','link','retry-after'} or k.startswith('x-ratelimit-')}
                self._write(path,{'endpoint':key,'headers':allowed,'body':payload,'checkpoint_sha256':round_key})
                delay=0
                if headers.get('retry-after') or headers.get('x-ratelimit-remaining')=='0':
                    delay=server_wait(headers,self.clock())
                    if not settings or delay is None or delay>settings.get('maximum_rate_wait_seconds',300):
                        self.stopped=True;self.stop_reason='acquisition-incomplete-rate-limited'
                self._finish(event,**fields,status='complete',outcome='success',response_sha256=sha(path),
                             global_stop_reason=self.stop_reason,required_wait_seconds=delay)
                if not self.stopped and delay:self._pause(delay)
                page=Page(payload,allowed,key);self.responses[key]=page;return page
            retryable=(rate or status is not None and 500<=status<=599 or connection_failure(error,stderr))
            # Every other 4xx is final even if the prose resembles a connection error.
            if status is not None and 400<=status<=499 and not rate:retryable=False
            delay=required_wait if rate else settings.get('backoff_base_seconds',1)*settings.get('backoff_factor',2)**(attempt-1)
            if retryable and not rate and 'retry-after' in headers:
                hint=server_wait(headers,self.clock())
                if hint is None or hint>settings.get('maximum_rate_wait_seconds',300):
                    self.stopped=True;self.stop_reason='acquisition-incomplete-rate-limited'
                    self._finish(event,**fields,status='failed',outcome=self.stop_reason,required_wait_seconds=hint);raise RateLimited()
                delay=max(delay,hint)
            again=bool(retryable and attempt<maximum)
            self._finish(event,**fields,status='failed',outcome='retry' if again else 'exhausted' if retryable else 'not-retryable',
                         retryable=bool(retryable),required_wait_seconds=required_wait,backoff_seconds=delay if again or rate else 0)
            if rate:self._pause(delay) # respect service cooldown even on the final attempt
            if not again:raise Incomplete('GET failed; repository acquisition incomplete')
            if not rate:self._budget(policy,key);self._pause(delay)
        raise AssertionError('Unreachable retry loop')


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
        self.client=client;self.repository=repository;self.cache={};self.ledger={};self.policy=policy;self.default_branch=default_branch;self.terminal_health=[];self.health_stopped=False;self.stages={};self.commit_cache={}
        if not hasattr(client,'pr_failures'):client.pr_failures={}
        self.failures=client.pr_failures.setdefault(repository,{})
        if not hasattr(client,'pr_metadata_cache'):client.pr_metadata_cache={}
        if not hasattr(client,'pr_commit_cache'):client.pr_commit_cache={}
        self.cache=client.pr_metadata_cache.setdefault(repository,{})
        self.commit_cache=client.pr_commit_cache.setdefault(repository,{})
    def _load(self,n):
        self.stages[n]='detail';self.ledger.setdefault(n,{})
        if self.health_stopped:raise RepositoryIncomplete('Terminal-event health stop: first 10 merged PR proofs failed')
        if n in self.cache:return self.cache[n]
        prefix=f'repos/{self.repository}/pulls/{n}'
        detail=self.client.get(prefix).body
        if not isinstance(detail,dict) or detail.get('number')!=n:raise Incomplete('PR detail mismatch')
        value={**detail,'_metadata_stage':'detail','_files_complete':False,'_timeline_complete':False}
        if self.policy and detail_filter(value,self.default_branch,self.policy):self.cache[n]=value;return value
        self.stages[n]='timeline'
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
        self.stages[n]='files'
        files,file_pages=pages(self.client,prefix+'/files',per_page=100)
        value.update(_metadata_stage='files',_files=files,_files_complete=len(files)==detail.get('changed_files'))
        self.cache[n]=value;self.ledger[n].update(file_pages=file_pages)
        return value
    def _commits(self,n,count):
        values,ledger=pages(self.client,f'repos/{self.repository}/pulls/{n}/commits',per_page=100)
        ids=[v['sha'] for v in values]
        if len(ids)!=count or len(set(ids))!=count:raise Incomplete('PR commit list incomplete')
        return ids,ledger


    @property
    def pr_failure_health_stopped(self):
        settings=(self.policy or {}).get('apparatus',{}).get('pr_isolation',{})
        return bool(settings.get('enabled') and len(self.failures)>=settings['maximum_failed_prs_per_repository'])

    def _health_check(self):
        if self.pr_failure_health_stopped:raise RepositoryIncomplete('PR failure health stop: five distinct PRs unavailable')

    def _failure(self,n,stage,error,begin):
        attempts=[dict(v) for v in getattr(self.client,'log',[])[begin:]]
        last=attempts[-1] if attempts else {}
        record={'number':n,'stage':stage,'status':'metadata-unavailable','reason':sanitize(str(error),getattr(self.client,'cache',Path.cwd())),
                'endpoint':last.get('endpoint'),'http_status':last.get('http_status'),'exit_status':last.get('exit_status'),'attempts':attempts}
        self.failures.setdefault(n,[]).append(record)
        self.ledger.setdefault(n,{})['metadata_unavailable']=record
        return record

    def load(self,n):
        self._health_check()
        if n in self.cache:return self.cache[n]
        begin=len(getattr(self.client,'log',[]))
        try:return self._load(n)
        except (Ceiling,RepositoryIncomplete):raise
        except Incomplete as error:
            if not (self.policy or {}).get('apparatus',{}).get('pr_isolation',{}).get('enabled'):raise
            record=self._failure(n,self.stages.get(n,'detail'),error,begin)
            stub={'number':n,'_metadata_status':'metadata-unavailable','_metadata_stage':record['stage'],'_metadata_unavailable':record}
            self.cache[n]=stub
            self._health_check()
            return stub

    def commits(self,n,count):
        self._health_check()
        if n in self.commit_cache:
            saved=self.commit_cache[n]
            if isinstance(saved,PRMetadataUnavailable):raise saved
            if saved[0]!=count:raise Incomplete('PR commit count changed')
            return saved[1]
        begin=len(getattr(self.client,'log',[]))
        try:
            result=self._commits(n,count);self.commit_cache[n]=(count,result);return result
        except (Ceiling,RepositoryIncomplete):raise
        except Incomplete as error:
            if not (self.policy or {}).get('apparatus',{}).get('pr_isolation',{}).get('enabled'):raise
            failure=PRMetadataUnavailable(self._failure(n,'commits',error,begin))
            self.commit_cache[n]=failure
            raise failure from error


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
