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
from .journal import selection_policy

ROOT=Path(__file__).resolve().parents[2]
READY='ready for checkpoint 1; collection requires matching authorization'

def runtime_pins():
    git=subprocess.check_output(['git','--version'],text=True).strip()
    match=re.search(r'git version (\d+)\.(\d+)',git)
    if not match or tuple(map(int,match.groups()))<(2,38):raise ValueError('Git >=2.38 required')
    return {'python_version':sys.version,'git_version':git}


M3_SHA256='f9c64ecbfa9a7939303b697287a317ba84cf72d3ad23d86f17832e839f3ae5b5'
# The authorized original round-2 checkpoint predates explicit M2 code pins.
# These exact bytes were verified against its source revision 0b47868; the
# compatibility map applies only to that checkpoint's exact SHA, never a generic
# missing field in a successor. No matching implementation is changed here.
LEGACY_ROUND2_CHECKPOINT='e99e8e0b99e35a89cbeef74520480c1cf7acabd7516676a78340967d70dcddb2'
LEGACY_M2_PINS={
    'benchmarks/s17/matching.py':'643f81c6ef41b7dfedfc1c1414f320a63cad4fd6c185de553dc29ce10d537a6f',
    'benchmarks/mut_v05_m2_audit.py':'8d093471b064dfff906dd2f0f8e175afff1af7905c52c1c6fe83a15fc901af28'}
PROTECTED_CODE=('benchmarks/s17b/selection.py','benchmarks/s17b/graph.py',
                'benchmarks/s17b/pipeline.py','benchmarks/s17/m3.py',*LEGACY_M2_PINS)


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def graph_pins():
    paths=list((ROOT/'benchmarks/s17b').glob('*.py'))+list((ROOT/'tests').glob('test_s17b_*.py'))
    paths += [ROOT/'docs/design/s17b-concurrent-pr.md',ROOT/'benchmarks/s17/m3.py',ROOT/'benchmarks/s17/__init__.py',
              ROOT/'conformance/git.py',ROOT/'conformance/__init__.py',ROOT/'benchmarks/s17b/policy.json',ROOT/'benchmarks/s17b/policy-round1.json',
              *[ROOT/name for name in LEGACY_M2_PINS]]
    return {p.relative_to(ROOT).as_posix():sha(p) for p in sorted(paths)}


def lineage(data):
    """Verify predecessor bytes; only apparatus.resume may change in a round."""
    hashes=set();current=data
    for _ in range(32):
        previous=current.get('predecessor')
        if previous is None:return hashes
        raw=previous['bytes'].encode()
        if hashlib.sha256(raw).hexdigest()!=previous['sha256']:raise ValueError('Predecessor hash drift')
        older=json.loads(raw)
        if selection_policy(current['policy'])!=selection_policy(older['policy']):raise ValueError('Predecessor selection policy/apparatus changed')
        for name in PROTECTED_CODE:
            before=older['code_sha256'].get(name)
            if before is None and previous['sha256']==LEGACY_ROUND2_CHECKPOINT:before=LEGACY_M2_PINS.get(name)
            if before is None or current['code_sha256'].get(name)!=before:raise ValueError('Protected predecessor code changed or missing: '+name)
        hashes.add(previous['sha256']);current=older
    raise ValueError('Predecessor chain too long')


def prepare(policy,destination,now=None,*,predecessor=None):
    now=now or datetime.now(timezone.utc)
    if timestamp(policy['collection_cutoff'])>now:raise ValueError('Cutoff must not exceed collection start')
    if not all(policy.get(k) for k in ('api_version','gh_version','detector_commit')):raise ValueError('Explicit API/gh/detector pins required')
    if policy.get('status')!=READY:raise ValueError('Explicit ready status required')
    if any(policy.get(k)!=v for k,v in runtime_pins().items()):raise ValueError('Python/Git runtime pins required and must match')
    if sha(ROOT/'benchmarks/s17/m3.py')!=M3_SHA256:raise ValueError('M3 changed')
    if policy['pair_order_seed']!='s17b-v1' or policy['pairs_per_repository']!=20:raise ValueError('Policy differs from accepted protocol')
    accepted=json.loads((ROOT/'benchmarks/s17b/policy.json').read_text())
    for key in ('terminal_lower','maximum_pairs','maximum_get_requests','maximum_git_bytes','maximum_measurement_seconds','repositories','per_repository_get_budget','per_repository_metadata_get_budget','per_repository_commits_get_budget','unallocated_get_allowance',
                'metadata_filter_order','unused_repository_budget','pr_commit_order','squash_corroboration',
                'terminal_tie','earlier_closed_unmerged','terminal_event_tolerance_seconds','terminal_event_proof',
                'terminal_health_stop','preordering','api_allowlist','clone','patch_policy','round_id','apparatus'):
        if policy.get(key)!=accepted[key]:raise ValueError('Policy protocol field changed: '+key)
    if sha(ROOT/'benchmarks/s17b/policy-round1.json')!=policy['apparatus']['round1_policy_sha256']:raise ValueError('Round-1 policy drift')
    if {k:v for k,v in policy.items() if k not in {'round_id','apparatus'}}!=json.loads((ROOT/'benchmarks/s17b/policy-round1.json').read_text()):raise ValueError('Round-1 selection policy changed')
    if sha(ROOT/'benchmarks/s17b/selection.py')!=policy['apparatus']['selection_source_sha256']:raise ValueError('Round-1 selection code drift')
    policy_sha=hashlib.sha256(json.dumps(policy,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    data={'stage':'checkpoint-1; no metadata collected','created_at':now.isoformat(),
          'policy':policy,'policy_sha256':policy_sha,'code_sha256':graph_pins(),'m3_sha256':M3_SHA256}
    if predecessor is not None:
        raw=Path(predecessor).read_bytes()
        data['predecessor']={'sha256':hashlib.sha256(raw).hexdigest(),'bytes':raw.decode()}
        lineage(data)
        data['stage']='checkpoint-1; acquisition successor; no oracle/detector/labels'
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
        lineage(data)
        if timestamp(data['policy']['collection_cutoff'])>timestamp(data['created_at']):raise ValueError('Checkpoint cutoff drift')
        if data['policy'].get('status')!=READY or any(data['policy'].get(k)!=v for k,v in runtime_pins().items()):raise ValueError('Checkpoint runtime/status drift')
        return data['policy']

    def cache_checkpoints(self):
        self.verify()
        return {sha(self.checkpoint),*lineage(json.loads(self.checkpoint.read_text()))}

    def prepare_clone(self,directory,repository,branch,expected,budget,**kwargs):
        from .acquire import prepare_clone
        return prepare_clone(directory=directory,repository=repository,branch=branch,expected=expected,
                             permit=self,budget=budget,**kwargs)
