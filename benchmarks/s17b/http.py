"""P6 GET transport classification and private journal sanitization only."""
import errno
from email.utils import parsedate_to_datetime
import os
from pathlib import Path
import re
import subprocess

from .selection import Ceiling


class RateLimited(Ceiling):
    def __init__(self):super().__init__('acquisition-incomplete-rate-limited')


def sanitize(value,cache):
    if isinstance(value,bytes):value=value.decode('utf-8','replace')
    value=str(value or '')
    for name in ('GH_TOKEN','GITHUB_TOKEN','GH_ENTERPRISE_TOKEN','GITHUB_ENTERPRISE_TOKEN'):
        if os.environ.get(name):value=value.replace(os.environ[name],'[REDACTED]')
    value=re.sub(r'(?im)(authorization\s*:\s*)([^\r\n]+)',r'\1[REDACTED]',value)
    value=re.sub(r'(?i)\b(?:bearer|token)\s+[A-Za-z0-9_./+=-]+','[REDACTED]',value)
    value=re.sub(r'\b(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+)\b','[REDACTED]',value)
    value=re.sub(r'(https?://)[^\s/@]+(?::[^\s/@]*)?@',r'\1[REDACTED]@',value)
    value=value.replace(str(Path(cache).resolve()),'${CACHE}').replace(str(Path.home()),'${HOME}')
    return value[:16384]+('[TRUNCATED]' if len(value)>16384 else '')


def parse_reply(stdout,stderr=''):
    if isinstance(stdout,bytes):stdout=stdout.decode('utf-8','replace')
    if isinstance(stderr,bytes):stderr=stderr.decode('utf-8','replace')
    head,separator,body=(stdout or '').replace('\r\n','\n').partition('\n\n')
    match=re.match(r'HTTP/\S+\s+(\d{3})(?:\s|$)',head)
    status=int(match[1]) if match else None
    headers={}
    if match:
        for line in head.splitlines()[1:]:
            if ':' in line:
                key,value=line.split(':',1);headers[key.lower()]=value.strip()
    if status is None:
        match=re.search(r'\(HTTP (\d{3})\)',stderr or '')
        if match:status=int(match[1])
    return status,headers,body if separator else None


def rate_response(status,headers):
    return status==429 or status==403 and ('retry-after' in headers or headers.get('x-ratelimit-remaining')=='0')


def server_wait(headers,now):
    try:
        if 'retry-after' in headers:
            raw=headers['retry-after']
            try:value=float(raw)
            except ValueError:value=parsedate_to_datetime(raw).timestamp()-now
        else:value=float(headers['x-ratelimit-reset'])-now
        import math
        return max(0,value) if math.isfinite(value) else None
    except (ValueError,TypeError,KeyError,OverflowError):return None


def connection_failure(error,stderr):
    if isinstance(error,(subprocess.TimeoutExpired,ConnectionError)):return True
    if isinstance(error,OSError):return error.errno in {errno.ECONNRESET,errno.ECONNREFUSED,errno.ETIMEDOUT,errno.ENETUNREACH,errno.EHOSTUNREACH,errno.ENETDOWN,errno.EPIPE}
    if isinstance(stderr,bytes):stderr=stderr.decode('utf-8','replace')
    return bool(re.search(r'(?i)connection (?:reset|refused|aborted)|(?:i/o|TLS handshake) timeout|network (?:is )?unreachable|no route to host|temporary failure in name resolution|no such host|failed to connect|error connecting to',stderr or ''))
