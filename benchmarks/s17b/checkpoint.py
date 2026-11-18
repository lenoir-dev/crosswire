"""Offline checkpoint creation. No acquisition is enabled by import or defaults."""
from dataclasses import dataclass
from datetime import datetime,timezone
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from .selection import timestamp

ROOT=Path(__file__).resolve().parents[2]
READY='ready for checkpoint 1; collection requires matching authorization'

def runtime_pins():
    git=subprocess.check_output(['git','--version'],text=True).strip()
    match=re.search(r'git version (\d+)\.(\d+)',git)
    if not match or tuple(map(int,match.groups()))<(2,38):raise ValueError('Git >=2.38 required')
    return {'python_version':sys.version,'git_version':git}


M3_SHA256='f9c64ecbfa9a7939303b697287a317ba84cf72d3ad23d86f17832e839f3ae5b5'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def graph_pins():
    paths=list((ROOT/'benchmarks/s17b').glob('*.py'))+list((ROOT/'tests').glob('test_s17b_*.py'))
    paths += [ROOT/'docs/design/s17b-concurrent-pr.md',ROOT/'benchmarks/s17/m3.py',ROOT/'benchmarks/s17/__init__.py',
              ROOT/'conformance/git.py',ROOT/'conformance/__init__.py',ROOT/'benchmarks/s17b/policy.json']
    return {p.relative_to(ROOT).as_posix():sha(p) for p in sorted(paths)}


def prepare(policy,destination,now=None):
    now=now or datetime.now(timezone.utc)
    if timestamp(policy['collection_cutoff'])>now:raise ValueError('Cutoff must not exceed collection start')
    if not all(policy.get(k) for k in ('api_version','gh_version','detector_commit')):raise ValueError('Explicit API/gh/detector pins required')
    if policy.get('status')!=READY:raise ValueError('Explicit ready status required')
    if any(policy.get(k)!=v for k,v in runtime_pins().items()):raise ValueError('Python/Git runtime pins required and must match')
    if sha(ROOT/'benchmarks/s17/m3.py')!=M3_SHA256:raise ValueError('M3 changed')
    if policy['pair_order_seed']!='s17b-v1' or policy['pairs_per_repository']!=20:raise ValueError('Policy differs from accepted protocol')
    accepted=json.loads((ROOT/'benchmarks/s17b/policy.json').read_text())
    for key in ('terminal_lower','maximum_pairs','maximum_get_requests','maximum_git_bytes','maximum_measurement_seconds','repositories','per_repository_get_budget','unallocated_get_allowance',
                'metadata_filter_order','unused_repository_budget','pr_commit_order','squash_corroboration',
                'terminal_tie','earlier_closed_unmerged','terminal_event_tolerance_seconds','terminal_event_proof',
                'terminal_health_stop','preordering','api_allowlist','clone','patch_policy'):
        if policy.get(key)!=accepted[key]:raise ValueError('Policy protocol field changed: '+key)
    policy_sha=hashlib.sha256(json.dumps(policy,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    data={'stage':'checkpoint-1; no metadata collected','created_at':now.isoformat(),
          'policy':policy,'policy_sha256':policy_sha,'code_sha256':graph_pins(),'m3_sha256':M3_SHA256}
    destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as stream:
        json.dump(data,stream,sort_keys=True,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    directory=os.open(destination.parent,os.O_RDONLY)
    try:os.fsync(directory)
    finally:os.close(directory)
    return data


@dataclass(frozen=True)
class Permit:
    checkpoint:Path
    authorization:Path

    def verify(self):
        data=json.loads(self.checkpoint.read_text());approval=json.loads(self.authorization.read_text())
        if approval.get('checkpoint_sha256')!=sha(self.checkpoint) or approval.get('scope')!='S17b read-only acquisition' or approval.get('approved_by')!='Polaris':
            raise PermissionError('Explicit matching Polaris acquisition authorization required')
        if data['code_sha256']!=graph_pins():raise ValueError('Checkpoint code drift')
        if timestamp(data['policy']['collection_cutoff'])>timestamp(data['created_at']):raise ValueError('Checkpoint cutoff drift')
        if data['policy'].get('status')!=READY or any(data['policy'].get(k)!=v for k,v in runtime_pins().items()):raise ValueError('Checkpoint runtime/status drift')
        return data['policy']

    def prepare_clone(self,*args,**kwargs):
        from .acquire import prepare_clone
        return prepare_clone(*args,permit=self,**kwargs)
