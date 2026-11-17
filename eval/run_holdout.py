"""Future-release-only holdout runner; v0.4 must never measure any holdout."""
import argparse
import json
from pathlib import Path
import re

from .integrity import verify_seal

SAFE_WORDS = set('micro repo_clustered95 by_rule exclusions oracle-ineligible source_sha256 manifest_sha256 eval_sha256 stratum mutation-holdout precision recall tp fp fn precision_wilson95 recall_wilson95 attribution_accuracy attribution_labelled eligible_cases unlabelled_predictions unlabelled_prediction_share unlabelled_cases unlabelled_share precision_gate recall_gate status measured insufficient data not estimable pass fail complete detector_errors precision_gate_lower_bound repositories replicates seed suppressed n reason_category_mismatches CW001 CW002 CW003 CW004 CW006'.split()) | {'insufficient data','not estimable'}


def assert_aggregate_only(value, field=None):
    """Allowlist keys AND prose values; hashes have no case-level labels."""
    if isinstance(value, dict):
        for key, item in value.items():
            assert key in SAFE_WORDS, 'Unknown/private aggregate key'
            assert_aggregate_only(item, key)
    elif isinstance(value,list):
        for item in value:
            assert_aggregate_only(item, field)
    elif isinstance(value,str):
        if field in {'source_sha256','manifest_sha256','eval_sha256'}:
            assert re.fullmatch('[0-9a-f]{64}',value), 'Invalid aggregate hash'
        else:
            assert value in SAFE_WORDS, 'Unknown/private aggregate value'
    else:
        assert value is None or isinstance(value,(bool,int,float)), 'Unsupported aggregate data'


def suppress_small_cells(value, minimum=5):
    """Suppress entire cells when any nonzero outcome can identify <5 cases.

    Also suppress parents containing such counts, to avoid subtraction disclosure.
    """
    if isinstance(value,dict):
        counts = [value[k] for k in ('tp','fp','fn','eligible_cases','unlabelled_cases','attribution_labelled','detector_errors') if isinstance(value.get(k),int)]
        if counts and (sum(counts)==0 or any(0<n<minimum for n in counts)):
            return {'status':'suppressed'}
        return {k:suppress_small_cells(v,minimum) for k,v in value.items()}
    if isinstance(value,list):
        return [suppress_small_cells(v,minimum) for v in value]
    if isinstance(value,int) and not isinstance(value,bool) and 0<value<minimum:
        return 'suppressed'
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-only',action='store_true')
    parser.add_argument('--private-dir',type=Path,default=Path.home()/'.crosswire-holdout/v2')
    parser.add_argument('--release',default='v0.4')
    parser.add_argument('--source-freeze-manifest',type=Path)
    parser.add_argument('--detector-python',default=__import__('sys').executable)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if not args.verify_only and args.release!='v0.5':
        parser.error('PLAN v0.4 R2 prohibits holdout measurement. First run requires explicit v0.5 authorization.')
    root=Path(__file__).resolve().parents[1]
    sealed=verify_seal(args.private_dir,root,root/'docs/validation/holdout.sha256')
    if args.verify_only:
        print(json.dumps({'status':'seal verified; not measured'}));return
    # This path is forbidden during v0.4, even if flags could enable it. A future
    # explicit architect authorization and immutable source manifest are required.
    if args.source_freeze_manifest is None or args.output is None:
        parser.error('Authorized v0.5 checkpoint requires source-freeze manifest and output')
    import hashlib,os
    from .measure import evaluate,report
    from .integrity import apparatus,digest
    source=root/'src'
    hashes={p.relative_to(root).as_posix():digest(p) for p in source.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    expected=json.loads(args.source_freeze_manifest.read_text())
    assert hashes==expected, 'Source does not match architect freeze manifest'
    # Create the attempt marker BEFORE invoking the detector: crashes consume the
    # attempt too. No repeat-and-tune path is available.
    marker=args.private_dir/'measurement-attempt.json'
    with marker.open('x') as f:json.dump({'release':args.release,'source_sha256':hashes},f,sort_keys=True)
    marker.chmod(0o600)
    rows=[evaluate(case,args.detector_python,source) for case in sealed['cases']]
    assert hashes=={p.relative_to(root).as_posix():digest(p) for p in source.rglob('*') if p.is_file() and '__pycache__' not in p.parts}, 'Source changed during measurement'
    raw=args.private_dir/'measurement-rows.json';raw.write_text(json.dumps(rows,sort_keys=True,indent=2));raw.chmod(0o600)
    summary=report(rows)
    summary.update(source_sha256=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest(),eval_sha256=hashlib.sha256(json.dumps(apparatus(root),sort_keys=True).encode()).hexdigest(),manifest_sha256=digest(args.private_dir/'manifest.json'),stratum='mutation-holdout')
    summary=suppress_small_cells(summary)
    assert_aggregate_only(summary)
    args.output.write_text(json.dumps(summary,sort_keys=True,indent=2)+'\n')
    print(json.dumps({'status':'complete'}))


if __name__=='__main__':main()
