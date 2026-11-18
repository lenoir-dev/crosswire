"""Acquisition-only counters; no checker, labels or source-derived verdicts."""
from collections import Counter
from urllib.parse import urlsplit

from .http import rate_response,connection_failure


def belongs(endpoint,repository):
    path=urlsplit(endpoint or '').path;prefix='repos/'+repository
    return path==prefix or path.startswith(prefix+'/')


def retry_cause(event):
    status=event.get('http_status')
    if rate_response(status,event.get('headers',{})):return 'rate-limit'
    if status is not None and 500<=status<=599:return 'http-5xx'
    if event.get('exception')=='TimeoutExpired':return 'timeout'
    if event.get('exception') in {'ConnectionError','ConnectionResetError','ConnectionAbortedError','ConnectionRefusedError'} or connection_failure(None,event.get('stderr','')):return 'connection'
    return 'other'


def repository_report(client,repository,slots=()):
    events=[e for e in getattr(client,'log',[]) if belongs(e.get('endpoint'),repository)]
    causes=Counter()
    for event in events:
        if event.get('operation_attempt',1)>1:
            prior=[e for e in events if e['request']<event['request'] and e['endpoint']==event['endpoint']]
            causes[retry_cause(max(prior,key=lambda e:e['request'])) if prior else 'unknown']+=1
    failures=getattr(client,'pr_failures',{}).get(repository,{})
    waits=[v for v in getattr(client,'wait_events',[]) if belongs(v.get('endpoint'),repository)]
    rescues=[s for s in slots if 'head_adjustment' in s or 'pre_update_rejection' in s]
    return {'pr_scoped_failures':len(failures),'pr_failures':failures,
            'retries':sum(causes.values()),'retries_by_cause':dict(causes),
            'wait_completed_seconds':sum(v['waited_seconds'] for v in waits),
            'wait_reserved_seconds':sum(v['planned_seconds'] for v in waits if not v['status'].startswith('blocked')),
            'wait_unconfirmed_seconds':sum(v['planned_seconds'] for v in waits if v['status']=='unconfirmed'),
            'blocked_waits':sum(v['status'].startswith('blocked') for v in waits),
            'pre_update_rescues':{'attempted':len(rescues),'accepted':sum(s.get('head_kind')=='pre-update' for s in rescues),
                'rejected':sum('pre_update_rejection' in s for s in rescues),
                'rejection_reasons':dict(Counter(s['pre_update_rejection'] for s in rescues if 'pre_update_rejection' in s))}}
