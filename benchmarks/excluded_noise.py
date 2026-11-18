"""Replay public oracle-ineligible cases; findings remain unlabelled, never TP/FP."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from eval.integrity import assert_case, git
from eval.paths import locations, resolve
from eval.portable import portable


def snapshot(directory):
    files = {p.relative_to(directory).as_posix():
             (p.readlink().as_posix() if p.is_symlink() else hashlib.sha256(p.read_bytes()).hexdigest(), p.lstat().st_mode)
             for p in directory.rglob('*') if p.is_file() and '.git' not in p.relative_to(directory).parts}
    return git(directory, 'rev-parse', 'HEAD'), git(directory, 'for-each-ref'), (directory / '.git/index').read_bytes(), files


def run(case, python):
    assert case['eligible'] is False, 'Eligible cases belong in the labelled measurement'
    assert_case(case)
    directory = Path(case['path'])
    before = snapshot(directory)
    command = [python, '-m', 'crosswire', 'check', '--repo', str(directory), '--target', case['target'],
               '--combined', '--no-cache', '--format', 'json', *case['tips']]
    row = {'id': case['id'], 'repository': case['repository'], 'oracle_eligible': False,
           'classification': 'unlabelled: oracle-ineligible', 'command': command}
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=60,
                                env=os.environ | {'PYTHONPATH': str(ROOT / 'src'), 'GIT_OPTIONAL_LOCKS': '0'})
        row.update(exit_code=result.returncode, stderr=result.stderr)
        if result.returncode not in (0, 1):
            row['detector_error'] = 'exit-error'
        else:
            row['report'] = json.loads(result.stdout)
            assert isinstance(row['report']['findings'], list)
    except subprocess.TimeoutExpired:
        row['detector_error'] = 'timeout'
    except (ValueError, UnicodeError, KeyError):
        row['detector_error'] = 'invalid-output'
    finally:
        assert snapshot(directory) == before, 'Detector modified excluded case'
        row['readonly_verified'] = True
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--detector-python', default=sys.executable)
    parser.add_argument('--output', type=Path, default=Path('docs/validation/v04-excluded-noise.json'))
    args = parser.parse_args()
    cases = [c for c in resolve(json.loads((ROOT / 'eval/development/cases.json').read_text()))['cases'] if not c['eligible']]
    source = ROOT / 'src'
    def hashes():
        return {p.relative_to(source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob('*.py')}
    before = hashes()
    with ThreadPoolExecutor(max_workers=3) as pool:
        rows = list(pool.map(lambda case: run(case, args.detector_python), cases))
    findings = [f for r in rows for f in r.get('report', {}).get('findings', [])]
    semantic = [f for f in findings if f['rule'] in {'CW001', 'CW002', 'CW006'}]
    summary = {'cases': len(rows), 'cases_with_findings': sum(bool(r.get('report', {}).get('findings')) for r in rows),
               'emitted_findings': len(findings), 'unlabelled_semantic_findings': len(semantic),
               'by_rule': {rule: sum(f['rule'] == rule for f in findings) for rule in sorted({f['rule'] for f in findings})},
               'detector_errors': sum('detector_error' in r for r in rows)}
    result = {'stratum': 'public oracle-ineligible detector replay; no semantic labels', 'source_commit': '3be5221',
              'source_sha256': before, 'source_stable': before == hashes(), 'summary': summary, 'rows': rows}
    assert result['source_stable']
    args.output.write_text(json.dumps(portable(result, locations()), indent=2, sort_keys=True) + '\n')
    print(json.dumps(summary))
    raise SystemExit(bool(summary['detector_errors']))


if __name__ == '__main__':
    main()
