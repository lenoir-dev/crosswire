"""H1: single authorized 0.5a attempt, private crash-safe rows, aggregate export.

The real invocation requires an architect-authorized immutable source archive.
Preparation/rehearsal must always supply an explicit synthetic private directory.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile

from .integrity import apparatus, digest, verify_seal

ORIGINAL_SEAL_SHA256 = '90c0a799531382e07b657bed4fe85a41941bba7af0d3100fe761982a4a2253d1'
SAFE_WORDS = set('micro repo_clustered95 by_rule exclusions oracle-ineligible source_sha256 manifest_sha256 eval_sha256 stratum mutation-holdout precision recall tp fp fn precision_wilson95 recall_wilson95 attribution_accuracy attribution_labelled eligible_cases unlabelled_predictions unlabelled_prediction_share unlabelled_cases unlabelled_share precision_gate recall_gate status measured insufficient data not estimable pass fail complete detector_errors precision_gate_lower_bound repositories replicates seed suppressed n reason_category_mismatches CW001 CW002 CW003 CW004 CW006 release 0.5a interrupted attempted_cases completed_cases failed_cases unattempted_cases'.split()) | {'insufficient data', 'not estimable', 'provisional pass', 'not evaluated'}
COUNT_FIELDS = {'tp','fp','fn','eligible_cases','unlabelled_cases','attribution_labelled',
                'detector_errors','unlabelled_predictions','reason_category_mismatches',
                'attempted_cases','completed_cases','failed_cases','unattempted_cases','oracle-ineligible'}
STAT_BLOCKS = {'micro','by_rule','repo_clustered95','exclusions',
               'attempted_cases','completed_cases','failed_cases','unattempted_cases'}


class AttemptConsumed(RuntimeError):
    """Neither a complete nor an interrupted attempt may execute the detector again."""


def assert_aggregate_only(value, field=None):
    """Allowlist keys AND prose values; no exception strings or case identities."""
    if isinstance(value, dict):
        for key, item in value.items():
            assert key in SAFE_WORDS, 'Unknown/private aggregate key'
            assert_aggregate_only(item, key)
    elif isinstance(value, list):
        for item in value:
            assert_aggregate_only(item, field)
    elif isinstance(value, str):
        if field in {'source_sha256','manifest_sha256','eval_sha256'}:
            assert re.fullmatch('[0-9a-f]{64}', value), 'Invalid aggregate hash'
        else:
            assert value in SAFE_WORDS, 'Unknown/private aggregate value'
    else:
        assert value is None or isinstance(value, (bool,int,float)), 'Unsupported aggregate data'
        assert not isinstance(value, float) or math.isfinite(value), 'Nonfinite aggregate'


def suppress_small_cells(value, minimum=5, _field=None):
    """Conservative complementary suppression: hide the linked statistical table.

    A small count in ANY statistical block hides micro, every rule, cluster and
    exclusion totals/ratios/intervals/gates together. Thus neither complements nor
    derived metrics reconstruct it. Provenance hashes/release/attempt status stay.
    Zero and the fixed repository-count metadata are not primary small outcomes.
    """
    def small(item, field=None):
        if isinstance(item, dict):
            return any(small(v,k) for k,v in item.items())
        if isinstance(item, list):
            return any(small(v,field) for v in item)
        return field in COUNT_FIELDS and type(item) is int and 0 < item < minimum
    if isinstance(value, dict):
        if 'micro' in value and 'by_rule' in value and any(small(value[k],k) for k in STAT_BLOCKS if k in value):
            return {k:({'status':'suppressed'} if k in STAT_BLOCKS else suppress_small_cells(v,minimum,k))
                    for k,v in value.items()}
        counts = [value[k] for k in COUNT_FIELDS-{'oracle-ineligible'} if type(value.get(k)) is int]
        if counts and (sum(counts)==0 or any(0 < n < minimum for n in counts)):
            return {'status':'suppressed'}
        return {k:suppress_small_cells(v,minimum,k) for k,v in value.items()}
    if isinstance(value, list):
        return [suppress_small_cells(v,minimum,_field) for v in value]
    if type(value) is int and 0 < value < minimum and _field not in {'repositories','replicates','seed'}:
        return 'suppressed'
    return value


def _directory_sync(directory):
    fd=os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_private(path, value, *, replace=False):
    """Exclusive create, or atomic status update; flush content AND directory."""
    data=(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
    path=Path(path)
    temporary=path.with_name(path.name+'.next') if replace else path
    fd=os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        if replace:
            os.replace(temporary,path)
        _directory_sync(path.parent)
    except BaseException:
        # An exclusive attempt marker is deliberately NEVER removed on failure.
        raise


def _canonical_sha(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


class AttemptJournal:
    def __init__(self, private):
        self.private=Path(private)
        self.directory=self.private/'measurement-journal'

    @classmethod
    def claim(cls, private, metadata):
        journal=cls(private)
        journal.private.chmod(0o700)
        try:
            _write_private(journal.private/'measurement-attempt.json',metadata)
        except FileExistsError as error:
            raise AttemptConsumed('Attempt consumed; report-only is permitted, detector rerun is not') from error
        journal.directory.mkdir(mode=0o700)
        _directory_sync(journal.private)
        journal.state('running')
        return journal

    def state(self, status, **details):
        _write_private(self.private/'measurement-state.json',{'status':status,**details},replace=True)

    def started(self, index, identity):
        _write_private(self.directory/f'{index:06d}.started.json',{'case_sha256':identity})

    def finished(self, index, identity, row):
        _write_private(self.directory/f'{index:06d}.result.json',{'case_sha256':identity,'row':row})

    def read(self, identities):
        rows=[];attempted=0;gap=False
        expected=set()
        for index,identity in enumerate(identities):
            start=self.directory/f'{index:06d}.started.json'
            result=self.directory/f'{index:06d}.result.json'
            if start.exists():
                if gap:
                    raise ValueError('Noncontiguous journal')
                attempted+=1;expected.add(start.name)
                if json.loads(start.read_text())['case_sha256']!=identity:
                    raise ValueError('Journal case identity mismatch')
                if result.exists():
                    raw=json.loads(result.read_text());expected.add(result.name)
                    if raw['case_sha256']!=identity:
                        raise ValueError('Journal result identity mismatch')
                    rows.append(raw['row'])
                else:
                    gap=True
            else:
                if result.exists():
                    raise ValueError('Journal result without start')
                gap=True
        if (set() if not self.directory.exists() else {p.name for p in self.directory.iterdir()}) != expected:
            raise ValueError('Unknown journal record')
        return rows,{'attempted_cases':attempted,'completed_cases':len(rows),
                     'failed_cases':attempted-len(rows),'unattempted_cases':len(identities)-attempted}


def _seal_entries(path):
    entries={}
    for line in Path(path).read_text().splitlines():
        sha,label=line.split('  ',1)
        if label in entries or not re.fullmatch('[0-9a-f]{64}',sha):
            raise ValueError('H1 malformed seal')
        entries[label]=sha
    return entries


def verify_h1_amendment(root, successor, *, rehearsal=False):
    """Original seal remains immutable; H1 changes ONLY this public runner."""
    original=root/'docs/validation/holdout.sha256'
    if digest(original)!=ORIGINAL_SEAL_SHA256:
        raise ValueError('H1 original seal mismatch')
    before=_seal_entries(original);after=_seal_entries(successor)
    changed={key for key in before if before[key]!=after.get(key)}
    allowed={'eval/run_holdout.py'}
    if rehearsal:
        allowed |= {'private/manifest.json','private/repositories.json'}
    if set(before)!=set(after) or not changed <= allowed or 'eval/run_holdout.py' not in changed:
        raise ValueError('H1 forbids changes outside the runner and rehearsal fixture pins')
    if after['eval/run_holdout.py']!=digest(root/'eval/run_holdout.py'):
        raise ValueError('H1 runner hash mismatch')


def holdout_report(rows, *, interrupted=False):
    """P1/M9 presentation only: underlying M1/M2 matching stays sealed."""
    from .measure import report
    summary=report(rows)
    for cell in summary['by_rule'].values():
        cell['precision_gate']=cell['recall_gate']='not evaluated'
        cell.pop('precision_gate_lower_bound',None)
    micro=summary['micro']
    if micro['precision_gate']=='pass':
        micro['precision_gate']='provisional pass'
    if interrupted:
        micro['precision_gate']=micro['recall_gate']='insufficient data'
        micro['status']='insufficient data'
    summary.update(release='0.5a',status='interrupted' if interrupted else 'complete')
    return summary


def _source_hashes(root):
    return {p.relative_to(root).as_posix():digest(p) for p in sorted((root/'src').rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}


def _recorded_inputs(private, root, successor):
    """Report-only binds immutable files, without re-opening case repositories.

    Native detector merges may add unreferenced Git objects. Whole-repository
    seal verification belongs BEFORE the attempt; reporting must not require
    restoring a repository, deleting objects or executing the detector again.
    """
    for label,expected in _seal_entries(successor).items():
        path=private/label.removeprefix('private/') if label.startswith('private/') else root/label
        if digest(path)!=expected:
            raise ValueError('Recorded input hash mismatch')
    return json.loads((private/'manifest.json').read_text())


def run_attempt(private, root, source_freeze, output, detector_python, successor, *, report_only=False, rehearsal=False):
    """No evaluator is reachable from report-only, even for a partial attempt."""
    private,root=Path(private),Path(root)
    if not report_only and (private/'measurement-attempt.json').exists():
        raise AttemptConsumed('Attempt consumed; detector rerun is prohibited')
    verify_h1_amendment(root,successor,rehearsal=rehearsal)
    sealed=_recorded_inputs(private,root,successor) if report_only else verify_seal(private,root,Path(successor))
    if rehearsal and sealed.get('synthetic_private_fixture') is not True:
        raise ValueError('Rehearsal requires explicit synthetic private fixtures')
    expected=json.loads(Path(source_freeze).read_text())
    hashes=_source_hashes(root)
    if not hashes or hashes!=expected:
        raise ValueError('Source does not match immutable architect freeze')
    identities=[_canonical_sha(case) for case in sealed['cases']]
    metadata={'release':'0.5a','n':len(identities),'manifest_sha256':digest(private/'manifest.json'),
              'source_sha256':_canonical_sha(hashes),'eval_sha256':_canonical_sha(apparatus(root)),
              'seal_sha256':digest(successor)}
    if report_only:
        recorded=json.loads((private/'measurement-attempt.json').read_text())
        if metadata!=recorded:
            raise ValueError('Journal attempt provenance mismatch')
        journal=AttemptJournal(private)
    else:
        from .measure import evaluate
        journal=AttemptJournal.claim(private,metadata)
        try:
            for index,(identity,case) in enumerate(zip(identities,sealed['cases'])):
                journal.started(index,identity)
                row=evaluate(case,detector_python,root/'src')
                journal.finished(index,identity,row)
            if hashes!=_source_hashes(root) or metadata['eval_sha256']!=_canonical_sha(apparatus(root)):
                raise ValueError('Frozen source/apparatus changed during attempt')
            journal.state('complete')
        except BaseException as error:
            journal.state('interrupted',error_type=type(error).__name__)
            raise
    rows,counts=journal.read(identities)
    state_path=private/'measurement-state.json'
    state=json.loads(state_path.read_text()) if state_path.exists() else {'status':'interrupted'}
    interrupted=len(rows)!=len(identities) or state['status']!='complete'
    # All partial evidence remains private; public metrics describe completed rows
    # explicitly and NEVER supply a full-cohort verdict after interruption.
    _write_private(private/'measurement-rows.json',rows,replace=True)
    summary=holdout_report(rows,interrupted=interrupted)
    summary.update(**counts,source_sha256=metadata['source_sha256'],eval_sha256=metadata['eval_sha256'],
                   manifest_sha256=metadata['manifest_sha256'],stratum='mutation-holdout')
    public=suppress_small_cells(summary)
    assert_aggregate_only(public)
    # An existing public output is never silently overwritten by a first attempt.
    _write_private(Path(output),public,replace=report_only)
    return public


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-only',action='store_true')
    parser.add_argument('--private-dir',type=Path,required=True)
    parser.add_argument('--release',default='v0.4')
    parser.add_argument('--source-freeze-manifest',type=Path)
    parser.add_argument('--detector-python',default=sys.executable)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--report-only',action='store_true',help='Export recorded rows; NEVER execute the detector')
    parser.add_argument('--rehearsal',action='store_true',help='Synthetic fixtures under the system temporary directory only')
    parser.add_argument('--rehearsal-seal',type=Path)
    args=parser.parse_args()
    if not args.verify_only and args.release!='0.5a':
        parser.error('PLAN v0.4 R2 prohibits holdout measurement; only separately authorized 0.5a is allowed')
    root=Path(__file__).resolve().parents[1]
    if args.rehearsal:
        if not args.private_dir.resolve().is_relative_to((Path(os.sep)/'tmp').resolve()):
            parser.error('Rehearsal private fixtures must be under the shared temporary directory')
        if args.rehearsal_seal is None:
            parser.error('Rehearsal requires its synthetic seal')
    elif args.rehearsal_seal is not None:
        parser.error('A custom seal is permitted only for a synthetic rehearsal')
    successor=args.rehearsal_seal or root/'docs/validation/holdout-v2-apparatus.sha256'
    if args.verify_only:
        verify_h1_amendment(root,successor,rehearsal=args.rehearsal)
        verify_seal(args.private_dir,root,successor)
        print(json.dumps({'status':'seal verified; not measured'}));return
    if args.source_freeze_manifest is None or args.output is None:
        parser.error('Authorized 0.5a requires source-freeze manifest and output')
    if (root/'.git').exists():
        parser.error('Measurement must run from the authorized immutable archive, not a checkout')
    try:
        summary=run_attempt(args.private_dir,root,args.source_freeze_manifest,args.output,
                            args.detector_python,successor,report_only=args.report_only,rehearsal=args.rehearsal)
    except AttemptConsumed:
        print(json.dumps({'status':'attempt consumed; report-only only'}),file=sys.stderr);raise SystemExit(2)
    except BaseException:
        # Detailed rows and the exception category are private. Do not print a
        # traceback whose paths/messages could disclose sealed case identities.
        print(json.dumps({'status':'attempt unavailable or interrupted; inspect private journal'}),file=sys.stderr)
        raise SystemExit(2)
    print(json.dumps({'status':summary['status']}))


if __name__=='__main__':main()
