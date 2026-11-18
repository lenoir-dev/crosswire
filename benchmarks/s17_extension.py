"""Outcome-blind supplemental cohort; reuses the unchanged frozen M3 apparatus."""
import argparse
import json
import subprocess
from pathlib import Path

from conformance.git import git
from benchmarks.s17 import run


CANDIDATES = [
    ('pluggy', 'pytest-dev/pluggy', 'plugin dispatch', ['src/pluggy', 'pluggy']),
    ('iniconfig', 'pytest-dev/iniconfig', 'INI parsing', ['src/iniconfig', 'iniconfig']),
    ('exceptiongroup', 'agronholm/exceptiongroup', 'exception compatibility', ['src/exceptiongroup', 'exceptiongroup']),
    ('outcome', 'python-trio/outcome', 'result containers', ['src/outcome', 'outcome']),
    ('h11', 'python-hyper/h11', 'HTTP/1 protocol', ['h11', 'src/h11']),
    ('async-generator', 'python-trio/async_generator', 'async language compatibility', ['async_generator', 'src/async_generator']),
    ('pykka', 'jodal/pykka', 'actor concurrency', ['pykka', 'src/pykka']),
    ('schedule', 'dbader/schedule', 'job scheduling', ['schedule', 'src/schedule']),
    ('toml', 'uiri/toml', 'TOML parsing', ['toml', 'src/toml']),
    ('sly', 'dabeaz/sly', 'parser generation', ['sly', 'src/sly']),
]
RULE = ('All ten declared candidates, latest four reachable two-parent merges since 2018-01-01 UTC '
        'with one merge-base different from both parents, a Python change and a clean native textual '
        'merge. Descending committer timestamp then SHA. Structural checks only, no checker or '
        'detector outcomes used. Every selected case is retained. No dependency or M3 changes. '
        'Supplement the original cohort; never replace its exclusions.')


def preregister(root, output):
    if (output/'selection.json').exists():
        raise ValueError('Extension already preregistered')
    repositories = []
    for name, github, domain, roots in CANDIDATES:
        repo = root/'repositories'/name
        url = 'https://github.com/'+github+'.git'
        if not repo.exists():
            subprocess.run(['git', 'clone', '--quiet', url, str(repo)], check=True, timeout=180)
        head = git(repo, 'rev-parse', 'HEAD').stdout.decode().strip()
        candidates = []
        lines = git(repo, 'rev-list', '--timestamp', '--min-parents=2', '--max-parents=2', '--parents', head).stdout.decode().splitlines()
        for line in lines:
            stamp, commit, *parents = line.split()
            if int(stamp) < 1514764800:
                continue
            bases = git(repo, 'merge-base', '--all', *parents).stdout.decode().splitlines()
            if len(bases) != 1 or bases[0] in parents:
                continue
            changed = git(repo, 'diff', '--name-only', bases[0], commit).stdout.decode().splitlines()
            if any(p.endswith('.py') for p in changed):
                candidates.append(dict(merge=commit, parents=parents, target=bases[0], timestamp=int(stamp)))
        candidates.sort(key=lambda c: (-c['timestamp'], c['merge']))
        chosen = []
        conflicts = 0
        for case in candidates:
            if len(chosen) == 4:
                break
            merged = git(repo, 'merge-tree', '--write-tree', *case['parents'], check=False)
            if merged.returncode:
                conflicts += 1
            else:
                chosen.append(case)
        repositories.append(dict(id=name, url=url, domain=domain, roots=roots, head=head,
                                 examined_two_parent_merges=len(lines), divergent_modern_python_merges=len(candidates),
                                 rejected_native_merge_failures=conflicts, cases=chosen))
        print(json.dumps(dict(repository=name, selected=len(chosen))), flush=True)
    run.write(output/'selection.json', dict(
        apparatus_freeze_sha256=run.sha(run.FREEZE), policy_sha256=run.sha(run.POLICY),
        extension_driver_sha256=run.sha(__file__), selection_rule=RULE,
        extension_of_sha256=run.sha(run.ROOT/'docs/validation/s17-natural/selection.json'),
        repositories=repositories, selected_cases=sum(len(s['cases']) for s in repositories)), root)
    print('Preregistered extension; no oracle run', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--preregister', action='store_true')
    parser.add_argument('--measure', action='store_true')
    parser.add_argument('--checker-python')
    parser.add_argument('--detector-python')
    args = parser.parse_args()
    root, output = args.root.resolve(), args.output.resolve()
    run.verify_freeze()
    if args.preregister:
        preregister(root, output)
    elif args.measure:
        if not args.checker_python or not args.detector_python:
            parser.error('Both installed interpreters required')
        selection = json.loads((output/'selection.json').read_text())
        if selection['extension_driver_sha256'] != run.sha(__file__):
            raise ValueError('Extension driver drift')
        if selection['extension_of_sha256'] != run.sha(run.ROOT/'docs/validation/s17-natural/selection.json'):
            raise ValueError('Original preregistration drift')
        run.measure(root, output, json.loads(run.POLICY.read_text()), args.checker_python, args.detector_python)
    else:
        parser.error('Choose --preregister or --measure')


if __name__ == '__main__':
    main()
