"""T22 implementation controls: native Git oracles and deterministic fault shims."""

import itertools
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys

import pytest

from crosswire import git

from .helpers import RepoBuilder


@pytest.fixture
def dag(repo):
    tree = repo.git('rev-parse', 'HEAD^{tree}').stdout.decode().strip()
    def commit(label, parents=()):
        args = ['commit-tree', tree, '-m', label]
        for parent in parents:
            args.extend(['-p', parent])
        return repo.git(*args).stdout.decode().strip()
    return commit


@pytest.fixture
def fake_git(tmp_path, monkeypatch):
    """Keep real Git for setup and select failures at its executable boundary."""
    real = shutil.which('git')
    directory = tmp_path / 'fake-bin'
    directory.mkdir()
    executable = directory / 'git'
    executable.write_text(
        f'#!{sys.executable}\n'
        'import os, subprocess, sys, time\n'
        f'real = {real!r}\n'
        'args = sys.argv[1:]\n'
        "mode = os.environ.get('T22_FAKE_GIT', '')\n"
        "if mode == 'old' and args == ['--version']:\n"
        "    print('git version 2.38.0'); sys.exit(0)\n"
        "if 'merge-tree' in args and '--stdin' in args:\n"
        "    if mode == 'old':\n"
        "        sys.stderr.write('error: unknown option stdin\\n'); sys.exit(129)\n"
        "    if mode == 'conflict-tree':\n"
        '        p = subprocess.run([real, *args], input=sys.stdin.buffer.read(), capture_output=True)\n'
        "        fields = p.stdout.split(b'\\0')\n"
        '        # Replace only the conflicted tree by a valid-looking wrong OID.\n'
        '        if len(fields) > 4: fields[4] = b"a" * len(fields[4])\n'
        "        sys.stdout.buffer.write(b'\\0'.join(fields)); sys.exit(p.returncode)\n"
        "if 'rev-list' in args and '--parents' in args:\n"
        "    if mode == 'stderr': sys.stderr.write('unexpected warning\\n'); time.sleep(5)\n"
        "    if mode == 'timeout': time.sleep(5)\n"
        "    if mode == 'bytes': sys.stdout.buffer.write(b'x' * 10000); sys.stdout.buffer.flush(); time.sleep(5)\n"
        "    if mode == 'exit': sys.exit(128)\n"
        'os.execv(real, [real, *args])\n'
    )
    executable.chmod(0o755)
    monkeypatch.setenv('PATH', str(directory) + os.pathsep + os.environ['PATH'])
    return directory


def _record(tree=b'a' * 40, status=b'1', paths=()):
    return status + b'\0' + tree + b'\0' + b''.join(path + b'\0' for path in paths) + b'\0'


def _result(raw):
    return subprocess.CompletedProcess(['git'], 0, raw, b'')


def test_first_16_then_256_boundary_preserves_every_pair(monkeypatch):
    tips = [f'{i:040x}' for i in range(1, 31)]
    pairs = list(itertools.combinations(tips, 2))
    requests = []
    monkeypatch.setattr(git._PairMerges, '_capable', lambda self: True)
    def batch(repo, args, cap, *, data):
        chunk = [tuple(line.decode().split()) for line in data.splitlines()]
        requests.append(chunk)
        return _result(b''.join(_record(status=b'0', paths=[f'p{pairs.index(pair)}'.encode()])
                                for pair in chunk))
    monkeypatch.setattr(git, '_bounded_git', batch)
    provider = git.pair_merges('.', tips)
    for index, pair in enumerate(pairs):
        assert provider.conflicts(*pair) == [f'p{index}']
    assert [len(chunk) for chunk in requests] == [16, 256, 163]
    assert list(itertools.chain.from_iterable(requests)) == pairs


@pytest.mark.parametrize('fault', ['exit', 'stderr', 'partial', 'status', 'oid', 'count', 'eof', 'cap'])
def test_failed_chunk_replays_lazily_and_disables_batching(monkeypatch, fault):
    tips = [f'{i:040x}' for i in range(1, 26)]
    pairs = list(itertools.combinations(tips, 2))
    monkeypatch.setattr(git._PairMerges, '_capable', lambda self: True)
    calls, serial = [], []
    def batch(repo, args, cap, *, data):
        calls.append(data)
        raw = _record() * len(data.splitlines())
        p = _result(raw)
        if fault == 'exit': p.returncode = 1
        elif fault == 'stderr': p.stderr = b'unexpected warning\n'
        elif fault == 'partial': p.stdout = raw[:len(raw) // 2]
        elif fault == 'status': p.stdout = b'7' + raw[1:]
        elif fault == 'oid': p.stdout = raw.replace(b'a' * 40, b'x' * 40, 1)
        elif fault == 'count': p.stdout += _record()
        elif fault == 'eof': p.stdout = raw[:-1]
        elif fault == 'cap': return None
        return p
    def scalar(repo, a, b):
        serial.append((a, b))
        if (a, b) == pairs[17]:
            raise git.GitError('serial error at pair 17')
        return ['serial']
    monkeypatch.setattr(git, '_bounded_git', batch)
    monkeypatch.setattr(git, 'merge_tree_conflicts', scalar)
    provider = git.pair_merges('.', tips)
    for index, pair in enumerate(pairs[:17]):
        assert provider.conflicts(*pair) == ['serial']
        assert serial == pairs[:index + 1]
    with pytest.raises(git.GitError, match='^serial error at pair 17$'):
        provider.conflicts(*pairs[17])
    assert len(calls) == 1
    assert provider.enabled is False and not provider.pending


def test_successful_first_chunk_then_failure_discards_all_later_results(monkeypatch):
    tips = [f'{i:040x}' for i in range(1, 26)]
    pairs = list(itertools.combinations(tips, 2))
    monkeypatch.setattr(git._PairMerges, '_capable', lambda self: True)
    calls, serial = [], []
    def batch(repo, args, cap, *, data):
        calls.append(data)
        return _result(_record() * 16) if len(calls) == 1 else None
    monkeypatch.setattr(git, '_bounded_git', batch)
    monkeypatch.setattr(git, 'merge_tree_conflicts', lambda repo, a, b: serial.append((a, b)) or [])
    provider = git.pair_merges('.', tips)
    for index, pair in enumerate(pairs):
        assert provider.conflicts(*pair) == []
        assert serial == pairs[16:index + 1]
    assert len(calls) == 2


def test_pair_mismatch_disables_without_substituting_result(monkeypatch):
    tips = [f'{i:040x}' for i in range(1, 4)]
    monkeypatch.setattr(git._PairMerges, '_capable', lambda self: True)
    monkeypatch.setattr(git, '_bounded_git', lambda *args, **kw: _result(_record() * 3))
    serial = []
    monkeypatch.setattr(git, 'merge_tree_conflicts', lambda repo, a, b: serial.append((a, b)) or ['serial'])
    provider = git.pair_merges('.', tips)
    assert provider.conflicts(tips[1], tips[0]) == ['serial']
    assert provider.enabled is False and not provider.pending
    assert provider.conflicts(tips[0], tips[2]) == ['serial']
    assert serial == [(tips[1], tips[0]), (tips[0], tips[2])]


@pytest.mark.parametrize('key', ['merge.custom.driver', 'filter.custom.clean', 'filter.custom.smudge',
                                 'filter.custom.process', 'extensions.partialclone', 'remote.origin.promisor'])
def test_configuration_guard_never_probes(repo, dag, monkeypatch, key):
    tips = [dag(str(i)) for i in range(3)]
    repo.git('config', key, 'true')
    def forbidden(*args):
        pytest.fail('configured command/promisor must prevent speculative work')
    monkeypatch.setattr(git, '_probe_pair_merges', forbidden)
    monkeypatch.setattr(git, 'merge_tree_conflicts', lambda *args: ['serial'])
    provider = git.pair_merges(repo.path, tips)
    assert provider.conflicts(*tips[:2]) == ['serial']
    assert provider.enabled is False


@pytest.mark.parametrize('fault', ['old', 'conflict-tree'])
def test_probe_failure_uses_scalar_path(repo, dag, fake_git, monkeypatch, fault):
    root = repo.git('rev-parse', 'HEAD').stdout.decode().strip()
    tips = [dag(str(i), [root]) for i in range(3)]
    monkeypatch.setenv('T22_FAKE_GIT', fault)
    provider = git.pair_merges(repo.path, tips)
    with repo.unchanged():
        assert provider.conflicts(*tips[:2]) == git.merge_tree_conflicts(repo.path, *tips[:2])
    assert provider.enabled is False
    if fault == 'old': assert git.git_version(repo.path) == (2, 38, 0)


def test_trace_stderr_disables_before_probe(repo, dag, monkeypatch, capsys):
    root = repo.git('rev-parse', 'HEAD').stdout.decode().strip()
    tips = [dag(str(i), [root]) for i in range(3)]
    monkeypatch.setenv('GIT_TRACE', '2')
    monkeypatch.setattr(git, '_probe_pair_merges', lambda *args: pytest.fail('trace must disable batching'))
    provider = git.pair_merges(repo.path, tips)
    with repo.unchanged():
        assert provider.conflicts(*tips[:2]) == []
    assert provider.enabled is False
    assert capsys.readouterr() == ('', '')


@pytest.mark.parametrize('length', [40, 64])
def test_probe_checks_clean_and_conflict_in_scratch(repo, monkeypatch, length):
    original = subprocess.Popen
    commands = []
    def record(args, *a, **kw):
        commands.append((args, Path(kw['cwd'])))
        return original(args, *a, **kw)
    before = set((repo.path / '.git/objects').rglob('*'))
    # A redirected user repository must never receive probe objects/refs.
    monkeypatch.setenv('GIT_DIR', str(repo.path / '.git'))
    monkeypatch.setattr(subprocess, 'Popen', record)
    assert git._probe_pair_merges(length)
    assert set((repo.path / '.git/objects').rglob('*')) == before
    scalar = [args for args, _ in commands if 'merge-tree' in args and '--stdin' not in args]
    assert len(scalar) == 2
    assert scalar[0][-2:] != scalar[1][-2:]
    assert len([args for args, _ in commands if '--stdin' in args and 'merge-tree' in args]) == 1
    assert all(cwd != repo.path and not cwd.exists() for _, cwd in commands)


def test_native_mixed_results_and_unreachable_objects(repo):
    commits = repo.named_dag({'shared.txt': 'base\n'}, {
        'a': ('target', {'shared.txt': 'left\n'}),
        'b': ('target', {'safe.txt': 'safe\n'}),
        'c': ('target', {'shared.txt': 'right\n'}),
    })
    tips = [commits[name] for name in 'abc']
    provider = git.pair_merges(repo.path, tips)
    objects = repo.path / '.git/objects'
    before = set(objects.rglob('*'))
    with repo.unchanged():
        assert provider.conflicts(*tips[:2]) == []
        assert provider.enabled
        # The conflict pair is still pending, but its objects can exist already.
        assert len(provider.pending) == 2
        assert set(objects.rglob('*')) > before
        for pair in itertools.combinations(tips, 2):
            assert git.merge_tree_conflicts(repo.path, *pair) == ([] if pair != (tips[0], tips[2]) else ['shared.txt'])
        assert provider.conflicts(tips[0], tips[2]) == ['shared.txt']
        assert provider.conflicts(tips[1], tips[2]) == []


def test_native_full_chunk_drains_input_and_output(repo, dag, monkeypatch):
    root = dag('root')
    tips = [dag(str(i), [root]) for i in range(25)]
    original = git._bounded_git
    chunks = []
    def record(directory, args, cap, **kwargs):
        if Path(directory) == repo.path and '--stdin' in args:
            chunks.append(len(kwargs['data'].splitlines()))
        return original(directory, args, cap, **kwargs)
    monkeypatch.setattr(git, '_bounded_git', record)
    provider = git.pair_merges(repo.path, tips)
    with repo.unchanged():
        assert all(provider.conflicts(*pair) == [] for pair in itertools.combinations(tips, 2))
    assert chunks == [16, 256, 28]


@pytest.mark.parametrize('seed', [22, 23, 24])
def test_seeded_graph_matches_all_native_best_bases(repo, dag, seed):
    rng = random.Random(seed)
    commits = []
    for index in range(35):
        parents = rng.sample(commits, min(len(commits), rng.randint(1, 3))) if index % 11 else []
        commits.append(dag(str(index), parents))
    tips = commits[-8:]
    provider = git.pair_bases(repo.path, tips)
    with repo.unchanged():
        for a, b in itertools.combinations(tips, 2):
            expected = repo.git('merge-base', '--all', a, b, check=False).stdout.decode().splitlines()
            assert provider.unique(a, b) == (expected[0] if len(expected) == 1 else None)
    assert provider.best


def test_criss_cross_and_unrelated_are_scalar_fallbacks(repo, dag):
    root = dag('root')
    left, right = dag('left', [root]), dag('right', [root])
    a, b = dag('a', [left, right]), dag('b', [right, left])
    unrelated = dag('unrelated')
    provider = git.pair_bases(repo.path, [a, b, unrelated, left])
    assert set(repo.git('merge-base', '--all', a, b).stdout.decode().splitlines()) == {left, right}
    assert provider.unique(a, b) is None
    assert provider.unique(a, unrelated) is None
    assert provider.unique(a, left) == left


@pytest.fixture
def small_graph(repo, dag):
    root = dag('root')
    tips = [dag(str(i), [root]) for i in range(4)]
    return root, tips


@pytest.mark.parametrize(('bound', 'value'), [('_MAX_TIPS', 3), ('_MAX_NODES', 1),
                                              ('_MAX_BYTES', 1), ('_SECONDS', 0)])
def test_all_capture_bounds_choose_scalar(repo, small_graph, monkeypatch, bound, value):
    _, tips = small_graph
    provider = git.pair_bases(repo.path, tips)
    monkeypatch.setattr(provider, bound, value)
    assert provider.unique(*tips[:2]) is None
    assert provider.best == {}


def test_construction_deadline_and_incomplete_graphs(repo, small_graph, monkeypatch):
    _, tips = small_graph
    raw = git._parent_graph(repo.path, tips, 100, 100000, 5)
    assert raw
    monkeypatch.setattr(git._PairBases, '_ordinary_history', lambda self: True)
    for malformed in (b'', raw[:-1], raw + raw.splitlines(keepends=True)[0], b'bad graph\n',
                      raw.replace(raw.split()[1], b'0' * 40, 1)):
        with monkeypatch.context() as patch:
            patch.setattr(git, '_parent_graph', lambda *args: malformed)
            assert git.pair_bases(repo.path, tips).unique(*tips[:2]) is None
    monkeypatch.setattr(git, '_parent_graph', lambda *args: raw)
    ticks = iter([0, 2])
    monkeypatch.setattr(git.time, 'monotonic', lambda: next(ticks))
    assert git.pair_bases(repo.path, tips).unique(*tips[:2]) is None


@pytest.mark.parametrize('name', ['GIT_GRAFT_FILE', 'GIT_SHALLOW_FILE', 'GIT_REPLACE_REF_BASE'])
def test_history_environment_guard(repo, small_graph, monkeypatch, name):
    _, tips = small_graph
    monkeypatch.setenv(name, 'unused')
    assert not git.pair_bases(repo.path, tips)._ordinary_history()


def test_replace_and_graft_guards(repo, small_graph):
    root, tips = small_graph
    repo.git('update-ref', 'refs/replace/' + tips[0], root)
    assert not git.pair_bases(repo.path, tips)._ordinary_history()
    repo.git('update-ref', '-d', 'refs/replace/' + tips[0])
    grafts = repo.path / '.git/info/grafts'
    grafts.write_text(tips[0] + '\n')
    assert not git.pair_bases(repo.path, tips)._ordinary_history()
    grafts.unlink()
    assert git.pair_bases(repo.path, tips)._ordinary_history()


def test_unreadable_info_is_scalar_fallback(repo, small_graph):
    _, tips = small_graph
    info = repo.path / '.git/info'
    info.chmod(0)
    try:
        if os.access(info, os.R_OK | os.X_OK):
            pytest.skip('process can bypass filesystem permission checks')
        assert git.pair_bases(repo.path, tips).unique(*tips[:2]) is None
        assert git.merge_base(repo.path, *tips[:2]) is not None
    finally:
        info.chmod(0o755)


@pytest.mark.parametrize('split', [False, True])
def test_commit_graph_count_skips_over_bound_before_walk(repo, small_graph, monkeypatch, split):
    _, tips = small_graph
    for i, sha in enumerate(tips): repo.git('update-ref', f'refs/heads/t{i}', sha)
    repo.git('commit-graph', 'write', '--reachable', *(['--split'] if split else []))
    assert git._commit_graph_count(repo.path / '.git') >= 5
    provider = git.pair_bases(repo.path, tips)
    monkeypatch.setattr(provider, '_MAX_NODES', 2)
    monkeypatch.setattr(git, '_parent_graph', lambda *args: pytest.fail('count should prevent walk'))
    assert provider.unique(*tips[:2]) is None


def test_sha256_native_graph_and_merges(tmp_path, monkeypatch):
    monkeypatch.setenv('GIT_DEFAULT_HASH', 'sha256')
    repo = RepoBuilder(tmp_path / 'sha256')
    for name, value in repo.env.items():
        if name.startswith('GIT_') or name == 'LC_ALL': monkeypatch.setenv(name, value)
    commits = repo.named_dag({}, {label: ('target', {label + '.txt': label}) for label in 'abcd'})
    tips = [commits[label] for label in 'abcd']
    assert all(len(sha) == 64 for sha in tips)
    bases, merges = git.pair_bases(repo.path, tips), git.pair_merges(repo.path, tips)
    with repo.unchanged():
        for pair in itertools.combinations(tips, 2):
            assert bases.unique(*pair) == commits['target']
            assert merges.conflicts(*pair) == git.merge_tree_conflicts(repo.path, *pair) == []
    assert merges.enabled


@pytest.mark.parametrize('fault', ['stderr', 'timeout', 'bytes', 'exit'])
def test_parent_capture_failure_kills_and_closes_every_pipe(repo, small_graph, fake_git, monkeypatch, fault):
    _, tips = small_graph
    monkeypatch.setenv('T22_FAKE_GIT', fault)
    original = subprocess.Popen
    processes = []
    def record(*a, **kw):
        p = original(*a, **kw)
        processes.append(p)
        return p
    monkeypatch.setattr(subprocess, 'Popen', record)
    assert git._parent_graph(repo.path, tips, 100, 100, 0.1 if fault == 'timeout' else 5) is None
    assert len(processes) == 1
    assert processes[0].poll() is not None
    assert processes[0].stdout.closed and processes[0].stderr.closed


def test_parent_capture_spawn_failure_is_invisible(repo, small_graph, monkeypatch):
    _, tips = small_graph
    def missing(*args, **kwargs):
        raise OSError('executable unavailable')
    monkeypatch.setattr(subprocess, 'Popen', missing)
    assert git._parent_graph(repo.path, tips, 100, 10000, 1) is None


def test_chunk_byte_cap_discards_and_reaps(repo, small_graph, monkeypatch):
    _, tips = small_graph
    monkeypatch.setattr(git._PairMerges, '_capable', lambda self: True)
    provider = git.pair_merges(repo.path, tips)
    monkeypatch.setattr(provider, '_MAX_BYTES', 1)
    original = subprocess.Popen
    processes = []
    def record(*a, **kw):
        p = original(*a, **kw)
        processes.append(p)
        return p
    monkeypatch.setattr(subprocess, 'Popen', record)
    with repo.unchanged():
        assert provider.conflicts(*tips[:2]) == []
    assert provider.enabled is False
    assert all(p.poll() is not None for p in processes)
    chunk = next(p for p in processes if '--stdin' in p.args)
    assert chunk.stdin.closed and chunk.stdout.closed and chunk.stderr.closed
