"""Deterministic T24 fixtures and an isolated, byte-preserving plan/RSS runner.

Example: python -B benchmarks/t24_blocked_plan.py --source-ref d01d5e6
         --output docs/validation/t24-baseline.json --work-root "${SCRATCH}"
No detector imports are used to construct or structurally validate fixtures.
"""
from __future__ import annotations

import argparse
import ast
import base64
from collections import Counter
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import platform
import resource
import shutil
import signal
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time


PROJECT = Path(__file__).resolve().parents[1]
FIXTURE_VERSION = 1
# Declared before measurement, never inferred/raised from observed stress costs.
# PLAN-v0.4 acceptance adopts docs/validation/v0.4.md's 1000(100)/30/plan cells.
BUDGETS = {
    'cold': {'p95_seconds': 2.95, 'worker_rss_mib': 40.40},
    'warm': {'p95_seconds': 2.28, 'worker_rss_mib': 30.75},
}
GAP = ''.join(f'# separator {i:02d}\n' for i in range(20))
WORKER = r'''
import atexit, json, resource, sys
source, metrics = sys.argv[1:3]
del sys.argv[1:3]
sys.path.insert(0, source)
def record():
    data = {'worker_self_peak_raw': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'worker_children_peak_raw': resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss}
    with open(metrics, 'w', encoding='utf-8') as stream:
        json.dump(data, stream)
atexit.register(record)
from crosswire.cli import main
raise SystemExit(main(sys.argv[1:]))
'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def environment():
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('GIT_', 'PYTHON', 'CROSSWIRE_', 'PYTEST_'))}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1',
               GIT_OPTIONAL_LOCKS='0', PYTHONDONTWRITEBYTECODE='1',
               PYTHONHASHSEED='0', LC_ALL='C', LANG='C', TZ='UTC')
    return env


def fixture_spec(kind):
    """Return a path-independent edit manifest for one 30-head fixture."""
    if kind not in ('a', 'b'):
        raise ValueError('fixture must be a or b')
    base = {f'assets/marker_{i:03d}.txt': f'stable asset {i}\n' for i in range(900)}
    for provider in range(8):
        base[f'providers/api_{provider}.py'] = f'# provider {provider}\ndef f(value):\n    return value + {provider}\n'
        for caller in range(10):
            base[f'consumers/call_{provider}_{caller}.py'] = (
                f'# consumer {provider}/{caller}\nfrom providers.api_{provider} import f\nresult = f(1)\n')
    base['shared.py'] = GAP.join(f'value_{i} = 0\n' for i in range(7))
    for i in range(11):
        base[f'filler_{i}.py'] = f'marker = {i}\n'
    safe_count = 21 if kind == 'a' else 22
    branches = []
    for i in range(safe_count):
        if kind == 'a' and i < 7:
            edits = {'shared.py': base['shared.py'].replace(f'value_{i} = 0', f'value_{i} = 1')}
        else:
            edits = {f'assets/marker_{i:03d}.txt': f'safe edit {i}\n'}
        branches.append({'name': f'safe_{i:02d}', 'parent': 'T', 'edits': edits})
    for i in range(8):
        branches.append({'name': f'break_{i:02d}', 'parent': 'T',
                         'edits': {f'providers/api_{i}.py': f'# removed f from provider {i}\nkeep = {i}\n'}})
    if kind == 'a':
        branches.append({'name': 'text_conflict', 'parent': 'T',
                         'edits': {'shared.py': base['shared.py'].replace('value_0 = 0', 'value_0 = 99')}})
    return {'version': FIXTURE_VERSION, 'kind': kind, 'target': 'T',
            'base': base, 'branches': branches}


def structural_check(spec):
    """Validate the split from literal edits/imports; no Git/detector oracle."""
    base, branches = spec['base'], spec['branches']
    assert len(base) == 1000 and sum(path.endswith('.py') for path in base) == 100
    assert len(branches) == 30 and len({b['name'] for b in branches}) == 30
    assert all(b['parent'] == 'T' for b in branches)
    callers = Counter()
    for path, text in base.items():
        assert not Path(path).is_absolute() and '..' not in Path(path).parts
        if not path.endswith('.py'):
            continue
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module != 'shared'
                if path.startswith('consumers/'):
                    assert node.module.startswith('providers.api_')
                    assert [alias.name for alias in node.names] == ['f']
                    callers[node.module] += 1
        if path.startswith('consumers/'):
            calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
            assert len(calls) == 1 and isinstance(calls[0].func, ast.Name)
            assert calls[0].func.id == 'f' and len(calls[0].args) == 1
    assert callers == Counter({f'providers.api_{i}': 10 for i in range(8)})
    for i in range(8):
        tree = ast.parse(base[f'providers/api_{i}.py'])
        funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
        assert len(funcs) == 1 and funcs[0].name == 'f' and len(funcs[0].args.args) == 1
    safe, broken, shared = [], [], []
    asset_paths = set()
    shared_nodes = ast.parse(base['shared.py']).body
    assert all(right.lineno - left.lineno > 6 for left, right in zip(shared_nodes, shared_nodes[1:]))
    base_values = {n.targets[0].id: n.value.value for n in shared_nodes}
    for branch in branches:
        assert len(branch['edits']) == 1
        path, text = next(iter(branch['edits'].items()))
        assert path in base and text != base[path]
        if path.startswith('providers/'):
            tree = ast.parse(text)
            assert not any(isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == 'f'
                           or isinstance(n, ast.Name) and n.id == 'f' for n in ast.walk(tree))
            broken.append(branch['name'])
        elif path == 'shared.py':
            tree = ast.parse(text)
            assert all(isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant) for n in tree.body)
            values = {n.targets[0].id: n.value.value for n in tree.body}
            assert values.keys() == base_values.keys()
            delta = [(name, value) for name, value in values.items() if value != base_values[name]]
            assert len(delta) == 1
            name, value = delta[0]
            if value == 1:
                shared.append(name)
                safe.append(branch['name'])
            else:
                assert (name, value) == ('value_0', 99)
                broken.append(branch['name'])
        else:
            assert path.startswith('assets/') and path not in asset_paths
            asset_paths.add(path)
            safe.append(branch['name'])
    expected = 21 if spec['kind'] == 'a' else 22
    assert len(safe) == expected and len(broken) == 30 - expected
    assert shared == ([f'value_{i}' for i in range(7)] if spec['kind'] == 'a' else [])
    assert [b['name'] for b in branches] == safe + broken
    return {'safe': safe, 'blocked': broken, 'first_party_consumers': sum(callers.values()),
            'shared_safe_regions': shared, 'files': len(base), 'python_files': 100,
            'expected_limit_hits': (['group_search_max_remaining', 'max_candidates']
                                    if spec['kind'] == 'a' else ['max_group'])}


def git(repo, *args, data=None):
    return subprocess.run(['git', *args], cwd=repo, env=environment(), input=data,
                          capture_output=True, check=True).stdout


def materialize(spec, repo):
    """Fast-import deterministic commits; refuse to reuse any existing repo."""
    split = structural_check(spec)
    repo.mkdir(parents=True)
    git(repo, 'init', '-b', 'T', '--object-format=sha1', '--template=')
    git(repo, 'config', 'gc.auto', '0')
    git(repo, 'config', 'core.autocrlf', 'false')
    git(repo, 'config', 'commit.gpgSign', 'false')
    stream = bytearray()

    def line(value):
        stream.extend(value.encode() + b'\n')

    def data(value):
        value = value.encode()
        line(f'data {len(value)}')
        stream.extend(value + b'\n')

    def commit(ref, mark, files, parent=None):
        line(f'commit refs/heads/{ref}')
        line(f'mark :{mark}')
        line('author Crosswire Benchmark <benchmark@example.invalid> 1000000000 +0000')
        line('committer Crosswire Benchmark <benchmark@example.invalid> 1000000000 +0000')
        data(f'T24 fixture v{FIXTURE_VERSION}: {ref}\n')
        if parent is not None:
            line(f'from :{parent}')
        for path, content in sorted(files.items()):
            line(f'M 100644 inline {path}')
            data(content)
        line('')

    commit('T', 1, spec['base'])
    for i, branch in enumerate(spec['branches'], 2):
        commit(branch['name'], i, branch['edits'], parent=1)
    line('done')
    git(repo, 'fast-import', '--quiet', '--date-format=raw', data=bytes(stream))
    git(repo, 'reset', '--hard', 'T')
    refs = git(repo, 'for-each-ref', '--format=%(refname:short) %(objectname)', 'refs/heads').decode()
    heads = dict(row.split() for row in refs.splitlines())
    labels = [b['name'] for b in spec['branches']]
    parents = git(repo, 'rev-list', '--no-walk', '--parents', *labels).decode().splitlines()
    assert all(row.split()[1:] == [heads['T']] for row in parents)
    return {'kind': spec['kind'], 'spec_sha256': sha(canonical(spec)), 'target': heads['T'],
            'heads': {name: heads[name] for name in labels}, 'labels': labels, **split}


def protected(repo):
    values = {}
    for directory, dirs, names in os.walk(repo):
        rel = Path(directory).relative_to(repo)
        if rel == Path('.git'):
            dirs[:] = [name for name in dirs if name not in ('objects', 'crosswire')]
        for name in names:
            path = Path(directory) / name
            values[str(path.relative_to(repo))] = [path.stat().st_mode, sha(path.read_bytes())]
    return values


def source_hashes(source):
    return {p.relative_to(source).as_posix(): sha(p.read_bytes())
            for p in sorted((source / 'src').rglob('*')) if p.is_file() and '__pycache__' not in p.parts}


def export_source(ref, destination):
    commit = git(PROJECT, 'rev-parse', f'{ref}^{{commit}}').decode().strip()
    archive = git(PROJECT, 'archive', commit, 'src')
    destination.mkdir()
    with tarfile.open(fileobj=io.BytesIO(archive)) as members:
        for member in members:
            path = Path(member.name)
            assert not path.is_absolute() and '..' not in path.parts
            if member.isdir():
                (destination / path).mkdir(parents=True, exist_ok=True)
            else:
                assert member.isfile()
                target = destination / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(members.extractfile(member).read())
    return commit


def supervisor(args):
    """One fresh supervisor per sample: CHILDREN high-water never carries over."""
    metrics_path = args.metrics.with_suffix('.worker.json')
    command = [sys.executable, '-B', '-S', '-P', '-c', WORKER,
               str(args.source / 'src'), str(metrics_path), 'plan', '--repo', 'repo',
               '--target', 'T', '--format', 'json', *args.labels]
    start = time.perf_counter()
    result = subprocess.run(command, cwd=args.fixture, env=environment(), capture_output=True)
    elapsed = time.perf_counter() - start
    metrics = json.loads(metrics_path.read_text())
    metrics['supervisor_children_peak_raw'] = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    metrics['worker_wall_seconds'] = elapsed
    metrics['exit'] = result.returncode
    args.metrics.write_text(json.dumps(metrics))
    # Preserve the CLI's two byte streams, without adding measurement markers.
    sys.stdout.buffer.write(result.stdout)
    sys.stderr.buffer.write(result.stderr)
    return result.returncode


def sample(fixture, source, metrics, timeout):
    command = [sys.executable, '-B', str(Path(__file__).resolve()), '--supervisor',
               '--fixture', str(fixture), '--source', str(source), '--metrics', str(metrics),
               '--labels', *json.loads((fixture / 'manifest.json').read_text())['labels']]
    start = time.perf_counter()
    process = subprocess.Popen(command, env=environment(), stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        return {'status': 'timeout', 'seconds_lower_bound': timeout}, None
    elapsed = time.perf_counter() - start
    usage = json.loads(metrics.read_text())
    unit = 1 if platform.system() == 'Darwin' else 1024
    values = {'status': 'ok' if process.returncode == 1 else 'error',
              'seconds': usage['worker_wall_seconds'], 'supervised_total_seconds': elapsed,
              'exit': process.returncode, 'stdout_sha256': sha(stdout), 'stderr_sha256': sha(stderr),
              **usage}
    for name in ('worker_self', 'worker_children', 'supervisor_children'):
        values[name + '_peak_bytes'] = int(usage[name + '_peak_raw'] * unit)
    return values, (process.returncode, stdout, stderr)


def output_summary(raw, manifest):
    code, stdout, stderr = raw
    assert code == 1 and stderr == b''
    obj = json.loads(stdout)
    safe = [name for step in obj['steps'] for name in step['branches']]
    blocked = [entry['branch'] for entry in obj['blocked']]
    assert safe == manifest['safe'] and blocked == manifest['blocked']
    assert obj['coverage'] == 'bounded' and obj['limits']['hit'] == manifest['expected_limit_hits']
    findings = [finding for entry in obj['blocked'] for finding in entry['findings']]
    return {'summary': obj['summary'], 'blocked_labels': blocked, 'safe_labels': safe,
            'findings': len(findings), 'by_rule': dict(Counter(f['rule'] for f in findings)),
            'inexact_findings': sum(not f['culprits_exact'] for f in findings),
            'coverage': obj['coverage'], 'limits': obj['limits'], 'limitations': obj['limitations']}


def run(args, work):
    source = work / 'source'
    commit = export_source(args.source_ref, source)
    sources = source_hashes(source)
    workspace_sources = source_hashes(PROJECT)
    benchmark_hash = sha(Path(__file__).read_bytes())
    report = {'version': 1, 'status': 'running', 'source_commit': commit,
              'source_sha256': sources, 'benchmark_sha256': benchmark_hash,
              'platform': platform.platform(), 'machine': platform.machine(),
              'python': sys.version, 'python_binary_sha256': sha(Path(sys.executable).resolve().read_bytes()),
              'git': git(PROJECT, '--version').decode().strip(), 'samples_per_cell': args.repeat,
              'timeout_seconds': args.timeout, 'rss_raw_units': 'bytes' if platform.system() == 'Darwin' else 'KiB',
              'rss_gate_metric': 'worker_self_peak_bytes',
              'rss_scope': 'worker SELF peak; supervisor CHILDREN is one worker per fresh supervisor, not a simultaneous process-tree peak',
              'wall_scope': 'worker startup/imports, plan, byte-stream capture and teardown; supervisor startup/metric writes excluded',
              'budget_declared_before_samples': True, 'proposed_budget': BUDGETS,
              'budget_source': 'docs/validation/v0.4.md: 1000(100)/30/plan cold and warm',
              'load_before': list(os.getloadavg()), 'fixtures': [], 'cells': []}
    def persist():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    persist()
    for kind in ('a', 'b'):
        directory = work / kind
        directory.mkdir()
        repo = directory / 'repo'
        manifest = materialize(fixture_spec(kind), repo)
        (directory / 'manifest.json').write_text(json.dumps(manifest, sort_keys=True))
        fixture_record = dict(manifest)
        report['fixtures'].append(fixture_record)
        original = protected(repo)
        expected = None
        for cache in ('cold', 'warm'):
            if cache == 'warm':
                preparation, raw = sample(directory, source, directory / 'warmup.json', args.timeout)
                assert preparation['status'] == 'ok' and raw == expected
                fixture_record['warm_preparation'] = preparation
            rows = []
            cell = {'fixture': kind, 'cache': cache, 'samples': rows}
            report['cells'].append(cell)
            for i in range(args.repeat):
                if cache == 'cold':
                    cache_path = repo / '.git' / 'crosswire' / 'cache'
                    if cache_path.exists():
                        shutil.rmtree(cache_path)
                values, raw = sample(directory, source, directory / f'{cache}-{i}.json', args.timeout)
                assert protected(repo) == original, 'fixture protected state changed'
                rows.append(values)
                if raw is not None and values['status'] == 'ok':
                    if expected is None:
                        expected = raw
                        fixture_record['outputs'] = {'exit': raw[0], 'stdout_base64': base64.b64encode(raw[1]).decode(),
                                                     'stderr_base64': base64.b64encode(raw[2]).decode()}
                        fixture_record['result'] = output_summary(raw, manifest)
                    assert raw == expected, 'CLI stdout/stderr/exit changed across samples'
                    # A relative --repo also keeps repro commands portable in raw captures.
                    assert str(work).encode() not in raw[1] + raw[2]
                    assert str(PROJECT).encode() not in raw[1] + raw[2]
                persist()
                print(f"fixture={kind} cache={cache} sample={i + 1} status={values['status']}", flush=True)
            complete = all(row['status'] == 'ok' for row in rows)
            times = [row['seconds'] for row in rows if row['status'] == 'ok']
            cell.update(p50_seconds=statistics.median(times) if complete else None,
                        p95_seconds=sorted(times)[math.ceil(.95 * len(times)) - 1] if complete else None,
                        peak_worker_rss_bytes=max((row.get('worker_self_peak_bytes', 0) for row in rows), default=0),
                        raw_outputs_stable=complete)
            cell['proposed_budget_verdict'] = ('pass' if complete and cell['p95_seconds'] <= BUDGETS[cache]['p95_seconds']
                and cell['peak_worker_rss_bytes'] <= BUDGETS[cache]['worker_rss_mib'] * 2**20 else 'fail')
            persist()
    report['load_after'] = list(os.getloadavg())
    report['source_stable'] = source_hashes(source) == sources
    report['benchmark_stable'] = sha(Path(__file__).read_bytes()) == benchmark_hash
    report['workspace_source_unchanged'] = source_hashes(PROJECT) == workspace_sources
    assert report['source_stable'] and report['benchmark_stable'] and report['workspace_source_unchanged']
    report['status'] = 'complete' if all(cell['raw_outputs_stable'] for cell in report['cells']) else 'insufficient'
    persist()
    return 0 if report['status'] == 'complete' else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-ref', default='d01d5e6')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--work-root', type=Path)
    parser.add_argument('--repeat', type=int, default=5)
    parser.add_argument('--timeout', type=float, default=600)
    parser.add_argument('--supervisor', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--fixture', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--source', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--metrics', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--labels', nargs='+', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.supervisor:
        return supervisor(args)
    if args.output is None or args.repeat < 5:
        parser.error('--output and at least five samples per cell are required')
    if args.work_root:
        work = args.work_root.resolve()
        if work.is_relative_to(PROJECT):
            parser.error('--work-root must be outside the project')
        work.mkdir(parents=True, exist_ok=True)
        if any(work.iterdir()):
            parser.error('--work-root must be empty; existing evidence is never removed')
        return run(args, work)
    with tempfile.TemporaryDirectory(prefix='crosswire-t24-') as directory:
        return run(args, Path(directory))


if __name__ == '__main__':
    raise SystemExit(main())
