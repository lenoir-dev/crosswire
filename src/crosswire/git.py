import atexit
import itertools
import os
import re
import selectors
import struct
import subprocess
import tempfile
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal


class GitError(Exception):
    pass


class SkippedBlob(Exception):
    """A source blob exceeds supported size or contains binary data."""
    def __init__(self, reason):
        self.reason = reason


@dataclass(frozen=True, slots=True)
class FileChange:
    status: Literal['A', 'M', 'D', 'R']
    path: str
    old_path: str | None = None


def _run(repo, *args, allowed=(0,)):
    env = os.environ.copy()
    env.update(GIT_OPTIONAL_LOCKS='0', LC_ALL='C')
    try:
        p = subprocess.run(['git', *args], cwd=repo,
                           capture_output=True, env=env)
    except (OSError, ValueError) as e:
        raise GitError(str(e)) from e
    if p.returncode not in allowed:
        raise GitError(p.stderr.decode('utf-8', 'replace').strip()
                       or f'git {args[0]} failed (exit {p.returncode})')
    return p


def repo_root(path):
    """Repo root."""
    bare = _run(path, 'rev-parse', '--is-bare-repository').stdout.strip() == b'true'
    if bare:
        return Path(path).resolve()
    return Path(os.fsdecode(_run(path, 'rev-parse', '--show-toplevel').stdout.rstrip(b'\n')))



def common_dir(repo):
    """Return the shared Git directory, including for linked worktrees."""
    raw = _run(repo, 'rev-parse', '--git-common-dir').stdout.rstrip(b'\n')
    path = Path(os.fsdecode(raw))
    return path if path.is_absolute() else (Path(repo) / path).resolve()


def git_version(repo):
    """Git version."""
    out = _run(repo, '--version').stdout.decode('ascii', 'replace')
    m = re.search(r'(\d+)\.(\d+)(?:\.(\d+))?', out)
    if not m:
        raise GitError('cannot determine git version')
    version = tuple(int(v or 0) for v in m.groups())
    if version < (2, 38, 0):
        raise GitError('Git 2.38 or newer is required')
    shallow = _run(repo, 'rev-parse', '--is-shallow-repository').stdout.strip()
    if shallow == b'true':
        raise GitError('shallow repository: fetch full history before analysis')
    return version


def resolve(repo, ref):
    """Resolve a user revision to a commit or report an unknown revision."""
    result = _run(repo, 'rev-parse', '--verify', '--end-of-options',
                  f'{ref}^{{commit}}', allowed=(0, 1, 128))
    if result.returncode:
        head = _run(repo, 'rev-parse', '--verify', 'HEAD^{commit}', allowed=(0, 1, 128))
        if head.returncode:
            raise GitError('unborn or empty repository: no HEAD commit')
        raise GitError(f'unknown revision: {ref}')
    return result.stdout.decode().strip()


@lru_cache(maxsize=32768)
def _merge_base_sha(repo, a, b):
    result = _run(repo, 'merge-base', a, b, allowed=(0, 1))
    return result.stdout.decode().strip() if result.returncode == 0 else None


def merge_base(repo, a, b):
    """Return a merge base, memoizing only immutable commit IDs."""
    if all(re.fullmatch(r'(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})', x) for x in (a, b)):
        return _merge_base_sha(str(repo), a, b)
    result = _run(repo, 'merge-base', a, b, allowed=(0, 1))
    return result.stdout.decode().strip() if result.returncode == 0 else None


def direct_parents(repo, commits):
    """Read direct parents of a batch of already-resolved commits."""
    if not commits:
        return {}
    result = _run(repo, 'rev-list', '--no-walk', '--parents', *commits)
    return {parts[0]: tuple(parts[1:]) for line in result.stdout.decode().splitlines()
            if (parts := line.split())}


def is_ancestor(repo, anc, desc):
    """Is ancestor."""
    return _run(repo, 'merge-base', '--is-ancestor', anc,
                desc, allowed=(0, 1)).returncode == 0


def changed_files(repo, base, tip):
    """Changed files."""
    parts = _run(
        repo,
        'diff',
        '--name-status',
        '-z',
        '-M',
        base,
        tip,
        '--').stdout.split(b'\0')
    result = []
    i = 0
    while i < len(parts) and parts[i]:
        status = parts[i][:1].decode('ascii')
        i += 1
        old = None
        if status in ('R', 'C'):
            old = os.fsdecode(parts[i])
            i += 1
        path = os.fsdecode(parts[i])
        i += 1
        if status == 'C':
            status, old = 'A', None
        if status == 'T':
            status = 'M'
        if status not in ('A', 'M', 'D', 'R'):
            raise GitError(f'unsupported diff status: {status}')
        result.append(FileChange(status, path, old))
    return result


class _BlobBatch:
    """One serialized cat-file stream for a repository."""

    def __init__(self, repo):
        env = os.environ.copy()
        env.update(GIT_OPTIONAL_LOCKS='0', LC_ALL='C')
        try:
            self.process = subprocess.Popen(['git', 'cat-file', '--batch-command', '-z'], cwd=repo,
                                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=subprocess.DEVNULL, env=env)
        except OSError as exc:
            raise GitError(str(exc)) from exc
        self.lock = threading.Lock()

    def read(self, rev, path):
        request = os.fsencode(f'{rev}:{path}' if path is not None else rev)
        if b'\0' in request:
            raise GitError('NUL in Git object path')
        with self.lock:
            try:
                self.process.stdin.write(b'info ' + request + b'\0')
                self.process.stdin.flush()
                header = self.process.stdout.readline()
                match = re.fullmatch(rb'[0-9a-fA-F]{40,64} ([a-z]+) ([0-9]+)\n', header)
                if match:
                    kind, size = match.group(1), int(match.group(2))
                    if kind != b'blob':
                        return None
                    if size > 2_000_000:
                        raise SkippedBlob('oversize')
                    self.process.stdin.write(b'contents ' + request + b'\0')
                    self.process.stdin.flush()
                    if self.process.stdout.readline() != header:
                        raise GitError('inconsistent git cat-file header')
                    content = self.process.stdout.read(size)
                    end = self.process.stdout.read(1)
                    if len(content) != size or end != b'\n':
                        raise GitError('truncated git cat-file response')
                    if kind != b'blob':
                        raise GitError(f'not a blob: {path}')
                    if b'\0' in content:
                        raise SkippedBlob('binary')
                    try:
                        return content.decode('utf-8', 'strict')
                    except UnicodeDecodeError as exc:
                        raise SkippedBlob('non-utf8') from exc
                expected = request + b' missing\n'
                if expected.startswith(header) and header:
                    rest = self.process.stdout.read(len(expected) - len(header))
                    if header + rest == expected:
                        return None
                raise GitError('invalid git cat-file response')
            except (BrokenPipeError, OSError, ValueError) as exc:
                raise GitError(f'git cat-file failed: {exc}') from exc

    def close(self):
        """Close the batch stream when the process exits."""
        try:
            if self.process.stdin:
                self.process.stdin.close()
            self.process.wait(timeout=1)
        except (OSError, subprocess.TimeoutExpired):
            self.process.kill()


_batches = OrderedDict()
_batches_lock = threading.Lock()
_MAX_BATCHES = 16


@lru_cache(maxsize=256)
def tree_entries(repo, rev):
    """Return tracked paths with modes and object IDs from an immutable tree."""
    entries = {}
    for entry in _run(repo, 'ls-tree', '-r', '-z', rev).stdout.split(b'\0'):
        if entry:
            metadata, _, path = entry.partition(b'\t')
            mode, _, oid = metadata.decode('ascii').split()
            entries[os.fsdecode(path)] = (mode, oid)
    return entries


def _read_batch(repo, rev, path):
    # The global lock also protects a stream from eviction while it is in use.
    key = str(Path(repo).resolve())
    with _batches_lock:
        batch = _batches.get(key)
        if batch is None or batch.process.poll() is not None:
            if batch is not None:
                _batches.pop(key)
                batch.close()
            while len(_batches) >= _MAX_BATCHES:
                _, evicted = _batches.popitem(last=False)
                evicted.close()
            batch = _BlobBatch(key)
            _batches[key] = batch
        _batches.move_to_end(key)
        return batch.read(rev, path)


def _close_batches():
    for batch in list(_batches.values()):
        batch.close()


atexit.register(_close_batches)


@lru_cache(maxsize=32768)
def _read_object(repo, oid):
    try:
        return _read_batch(repo, oid, None)
    except SkippedBlob as exc:
        return exc


def read_blob(repo, oid):
    """Read a known blob ID without expanding its containing tree."""
    value = _read_object(str(repo), oid)
    if isinstance(value, SkippedBlob):
        raise value
    return value


def entries_for_paths(repo, rev, paths):
    """Read tree metadata only for the selected analysis paths."""
    if not paths:
        return {}
    entries = {}
    for entry in _run(repo, 'ls-tree', '-r', '-z', rev, '--', *sorted(paths)).stdout.split(b'\0'):
        if entry:
            metadata, _, path = entry.partition(b'\t')
            mode, _, oid = metadata.decode('ascii').split()
            entries[os.fsdecode(path)] = (mode, oid)
    return entries


def read_file(repo, rev, path):
    """Read a bounded UTF-8 blob, sharing identical objects across Git states."""
    if re.fullmatch(r'(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})', rev):
        entry = tree_entries(str(repo), rev).get(path)
        if entry is None or entry[0] == '160000':
            return None
        value = _read_object(str(repo), entry[1])
        if isinstance(value, SkippedBlob):
            raise value
        return value
    return _read_batch(repo, rev, path)


@lru_cache(maxsize=8192)
def _list_files_sha(repo, rev, prefix):
    return tuple(_list_files(repo, rev, prefix))


def _list_files(repo, rev, prefix):
    args = ['ls-tree', '-r', '-z', '--name-only', rev]
    if prefix:
        args += ['--', prefix]
    return [os.fsdecode(x) for x in _run(repo, *args).stdout.split(b'\0') if x]


def list_files(repo, rev, prefix=''):
    """List tracked files, caching only immutable revisions."""
    if re.fullmatch(r'(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})', rev):
        return list(_list_files_sha(str(repo), rev, prefix))
    return _list_files(repo, rev, prefix)


def merge_tree_conflicts(repo, a, b):
    """Merge tree conflicts."""
    p = _run(
        repo,
        'merge-tree',
        '--write-tree',
        '--name-only',
        '-z',
        '--no-messages',
        a,
        b,
        allowed=(
            0,
            1))
    parts = p.stdout.split(b'\0')
    if not re.fullmatch(rb'(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})', parts[0]):
        raise GitError(p.stderr.decode('utf-8', 'replace').strip()
                       or 'git merge-tree failed: invalid tree object ID')
    if p.returncode == 0:
        return []
    return sorted({os.fsdecode(x) for x in parts[1:] if x})


def _try_git(repo, args, *, data=None):
    """Speculative work never owns diagnostics or changes their evaluation order."""
    env = os.environ.copy()
    env.update(GIT_OPTIONAL_LOCKS='0', LC_ALL='C')
    try:
        return subprocess.run(['git', *args], cwd=repo, env=env, input=data,
                              capture_output=True)
    except (OSError, ValueError):
        return None


def _merge_records(result, count, oid_length):
    """Validate the complete stdin protocol before trusting any of a chunk."""
    if result is None or result.returncode != 0 or result.stderr:
        return None
    parts = result.stdout.split(b'\0')
    records = []
    cursor = 0
    for _ in range(count):
        if cursor + 2 >= len(parts):
            return None
        status, tree = parts[cursor:cursor + 2]
        cursor += 2
        if status not in (b'0', b'1') or tree == b'0' * oid_length or not re.fullmatch(
                rb'[0-9a-f]{' + str(oid_length).encode() + rb'}', tree):
            return None
        paths = []
        while cursor < len(parts) and parts[cursor]:
            paths.append(os.fsdecode(parts[cursor]))
            cursor += 1
        if cursor >= len(parts) or (status == b'1' and paths):
            return None
        cursor += 1
        records.append((status, tree, sorted(set(paths))))
    return records if parts[cursor:] == [b''] else None


class _PairMerges:
    """Run-scoped, bounded speculation for independent, ordered pair merges.

    Only the original serial call may raise or print an operational diagnostic.
    In particular, a failed chunk cannot leave partially trusted results behind.
    Dependent virtual integration continues to use its existing implementation.
    Speculation can write unreachable objects for later pairs even if analysis
    stops early. The first chunk contains 16 pairs; later chunks contain 256.
    """

    _CHUNK_SIZE = 256
    _FIRST_CHUNK = 16
    _MAX_BYTES = 64 * 1024 * 1024
    _ARGS = ('merge-tree', '--stdin', '--write-tree', '--name-only', '-z', '--no-messages')

    def __init__(self, repo, commits):
        self.repo = repo
        self.commits = tuple(commits)
        self.requests = itertools.combinations(self.commits, 2)
        self.pending = deque()
        self.enabled = None
        self.first = True

    def _capable(self):
        # External drivers, filters and lazy promisor fetches can have
        # observable side effects. Never invoke them speculatively.
        config = _try_git(self.repo, ['config', '--null', '--get-regexp',
            r'^(merge\..*\.driver|filter\..*\.(clean|smudge|process)'
            r'|extensions\.partialclone|remote\..*\.promisor)$'])
        return (config is not None and config.returncode == 1
                and not config.stdout and not config.stderr
                and _probe_pair_merges(len(self.commits[0])))

    def conflicts(self, a, b):
        if self.enabled is None:
            # A single pair cannot amortize the configuration/capability probe.
            self.enabled = len(self.commits) >= 3 and self._capable()
        if self.enabled:
            if not self.pending:
                size = self._FIRST_CHUNK if self.first else self._CHUNK_SIZE
                self.first = False
                chunk = list(itertools.islice(self.requests, size))
                data = ''.join(f'{left} {right}\n' for left, right in chunk).encode('ascii')
                result = _bounded_git(self.repo, self._ARGS, self._MAX_BYTES, data=data)
                records = _merge_records(result, len(chunk), len(a))
                if records is None:
                    self.enabled = False
                else:
                    self.pending.extend((pair, records[i][2]) for i, pair in enumerate(chunk))
            if self.pending:
                pair, paths = self.pending.popleft()
                if pair == (a, b):
                    if paths is not None:
                        return paths
                else:
                    # Keep this helper conservative if a caller changes its
                    # traversal; never substitute a result in another direction.
                    self.enabled = False
                    self.pending.clear()
        return merge_tree_conflicts(self.repo, a, b)


def _bounded_git(repo, args, max_bytes, *, seconds=None, data=None, env=None):
    """Drain all pipes, cap stdout, and kill/reap discarded speculation."""
    if env is None:
        env = os.environ.copy()
        env.update(GIT_OPTIONAL_LOCKS='0', LC_ALL='C')
    deadline = time.monotonic() + seconds if seconds is not None else None
    process = None
    try:
        process = subprocess.Popen(
            ['git', *args],
            cwd=repo, env=env, stdin=subprocess.PIPE if data else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output = bytearray()
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, 'stdout')
            selector.register(process.stderr, selectors.EVENT_READ, 'stderr')
            if data:
                os.set_blocking(process.stdin.fileno(), False)
                selector.register(process.stdin, selectors.EVENT_WRITE, 'stdin')
            sent = 0
            while selector.get_map():
                remaining = deadline - time.monotonic() if deadline is not None else None
                if remaining is not None and remaining <= 0:
                    return None
                for key, _ in selector.select(remaining):
                    if key.data == 'stdin':
                        try:
                            sent += os.write(key.fd, data[sent:sent + 65536])
                        except BlockingIOError:
                            continue
                        if sent == len(data):
                            selector.unregister(key.fileobj)
                            process.stdin.close()
                        continue
                    block = os.read(key.fd, 65536)
                    if not block:
                        selector.unregister(key.fileobj)
                    elif key.data == 'stderr':
                        return None
                    else:
                        output.extend(block)
                        if len(output) > max_bytes:
                            return None
        remaining = deadline - time.monotonic() if deadline is not None else None
        if (remaining is not None and remaining <= 0) or process.wait(timeout=remaining) != 0:
            return None
        return subprocess.CompletedProcess(['git', *args], 0, bytes(output), b'')
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait()
            process.stdout.close()
            process.stderr.close()
            if process.stdin is not None:
                process.stdin.close()


def _parent_graph(repo, commits, max_nodes, max_bytes, seconds):
    """Capture a bounded, complete parent walk or discard all speculation."""
    result = _bounded_git(repo, ['rev-list', '--topo-order', '--parents',
        f'--max-count={max_nodes + 1}', *commits], max_bytes, seconds=seconds)
    return result.stdout if result is not None else None


def _probe_pair_merges(oid_length):
    """Prove clean AND conflicted framing outside the user's object store."""
    # Repository redirection/configuration must not escape the disposable repo.
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_OPTIONAL_LOCKS='0', LC_ALL='C')
    def run(repo, args, data=None):
        try:
            return subprocess.run(['git', *args], cwd=repo, env=env, input=data,
                                  capture_output=True)
        except (OSError, ValueError):
            return None
    try:
        with tempfile.TemporaryDirectory(prefix='crosswire-merge-probe-') as directory:
            init = run(directory, ['init', '--bare', '--quiet',
                '--object-format=' + ('sha256' if oid_length == 64 else 'sha1')])
            if init is None or init.returncode or init.stderr:
                return False
            stream = bytearray()
            for index, content in enumerate((b'base\n', b'left\n', b'right\n'), 1):
                stream.extend(f'blob\nmark :{index}\ndata {len(content)}\n'.encode() + content)
                stream.extend(f'commit refs/heads/p{index}\nmark :{index + 3}\n'
                    'committer crosswire <crosswire@invalid> 0 +0000\ndata 1\nx\n'.encode())
                if index > 1:
                    stream.extend(b'from :4\n')
                stream.extend(f'M 100644 :{index} conflict.txt\n\n'.encode())
            marks = Path(directory) / 'probe-marks'
            imported = run(directory, ['fast-import', '--quiet', f'--export-marks={marks}'], bytes(stream))
            if imported is None or imported.returncode or imported.stderr:
                return False
            ids = dict(line.split() for line in marks.read_text(encoding='ascii').splitlines())
            pairs = [(ids[':4'], ids[':5']), (ids[':5'], ids[':6'])]
            expected = []
            for (a, b), code in zip(pairs, (0, 1)):
                scalar = run(directory, ['merge-tree', '--write-tree', '--name-only', '-z',
                                          '--no-messages', a, b])
                if scalar is None or scalar.returncode != code or scalar.stderr:
                    return False
                fields = scalar.stdout.split(b'\0')
                if not re.fullmatch(rb'[0-9a-f]{' + str(oid_length).encode() + rb'}', fields[0]):
                    return False
                expected.append((b'1' if code == 0 else b'0', fields[0],
                                 sorted({os.fsdecode(path) for path in fields[1:] if path})))
            result = _bounded_git(directory, _PairMerges._ARGS, _PairMerges._MAX_BYTES,
                data=''.join(f'{a} {b}\n' for a, b in pairs).encode('ascii'), env=env)
            return _merge_records(result, 2, oid_length) == expected
    except (OSError, ValueError, KeyError):
        return False


def _commit_graph_count(directory):
    """Read only fanout metadata; an overestimate merely disables an optimization."""
    try:
        graph = directory / 'objects/info/commit-graph'
        if graph.is_file():
            paths = [graph]
        else:
            chain = directory / 'objects/info/commit-graphs/commit-graph-chain'
            if not chain.is_file() or chain.stat().st_size > 64 * 1024:
                return None
            hashes = chain.read_text(encoding='ascii').splitlines()
            if not hashes or any(not re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', h) for h in hashes):
                return None
            paths = [chain.parent / f'graph-{h}.graph' for h in hashes]
        total = 0
        for path in paths:
            with path.open('rb') as stream:
                header = stream.read(8)
                if len(header) != 8 or header[:6] not in (b'CGPH\x01\x01', b'CGPH\x01\x02'):
                    return None
                table = stream.read((header[6] + 1) * 12)
                if len(table) != (header[6] + 1) * 12:
                    return None
                offsets = [(table[i:i + 4], struct.unpack('>Q', table[i + 4:i + 12])[0])
                           for i in range(0, len(table), 12)]
                fanout = next((offset for name, offset in offsets if name == b'OIDF'), None)
                if fanout is None or fanout < 8 + len(table):
                    return None
                stream.seek(fanout + 255 * 4)
                count = stream.read(4)
                if len(count) != 4:
                    return None
                total += struct.unpack('>I', count)[0]
        return total
    except (OSError, UnicodeError, ValueError):
        return None


class _PairBases:
    """Prove unique best common ancestors; preserve scalar choices otherwise."""

    _MAX_TIPS = 64
    _MAX_NODES = 20_000
    _MAX_BYTES = 4 * 1024 * 1024
    _SECONDS = 1.0

    def __init__(self, repo, commits):
        self.repo = repo
        self.bits = {sha: 1 << i for i, sha in enumerate(commits)}
        self.best = None

    def _ordinary_history(self):
        if any(name in os.environ for name in ('GIT_GRAFT_FILE', 'GIT_SHALLOW_FILE', 'GIT_REPLACE_REF_BASE')):
            return False
        location = _try_git(self.repo, ['rev-parse', '--git-common-dir'])
        if location is None or location.returncode != 0 or location.stderr:
            return False
        directory = Path(os.fsdecode(location.stdout.rstrip(b'\n')))
        if not directory.is_absolute():
            directory = Path(self.repo) / directory
        try:
            unsupported = (directory / 'info/grafts').exists() or (directory / 'shallow').exists()
        except OSError:
            # Metadata access is speculative too; only scalar Git owns errors.
            return False
        if unsupported:
            return False
        count = _commit_graph_count(directory)
        if count is not None and count > self._MAX_NODES:
            return False
        replacements = _try_git(self.repo, ['for-each-ref', '--format=%(refname)', 'refs/replace/'])
        if replacements is None or replacements.returncode != 0 or replacements.stderr or replacements.stdout:
            return False
        partial = _try_git(self.repo, ['config', '--null', '--get-regexp',
                                      r'^(extensions\.partialclone|remote\..*\.promisor)$'])
        return partial is not None and partial.returncode == 1 and not partial.stdout and not partial.stderr

    def _build(self):
        if not 4 <= len(self.bits) <= self._MAX_TIPS or not self._ordinary_history():
            return {}
        raw = _parent_graph(self.repo, self.bits, self._MAX_NODES, self._MAX_BYTES, self._SECONDS)
        if raw is None or len(raw) > self._MAX_BYTES or not raw.endswith(b'\n'):
            return {}
        deadline = time.monotonic() + self._SECONDS
        rows = []
        positions = {}
        oid_length = len(next(iter(self.bits)))
        oid = re.compile(rb'[0-9a-f]{' + str(oid_length).encode() + rb'}')
        for line in raw.splitlines():
            fields = line.split()
            if (not fields or len(rows) >= self._MAX_NODES or time.monotonic() >= deadline
                    or any(not oid.fullmatch(value) for value in fields)):
                return {}
            sha, *parents = (value.decode('ascii') for value in fields)
            if sha in positions:
                return {}
            positions[sha] = len(rows)
            rows.append((sha, parents))
        if not self.bits.keys() <= positions.keys():
            return {}
        for sha, parents in rows:
            if time.monotonic() >= deadline:
                return {}
            if any(parent not in positions or positions[parent] <= positions[sha] for parent in parents):
                return {}
        masks = dict(self.bits)
        children = {}
        best = {}
        for sha, parents in rows:
            if time.monotonic() >= deadline:
                return {}
            mask = masks.get(sha, 0)
            child_masks = children.pop(sha, set())
            # A common descendant makes an immediate child common too. This
            # node is a best base exactly when no child reaches both tips.
            if mask.bit_count() > 1 and mask not in child_masks:
                selected = [bit for bit in self.bits.values() if mask & bit]
                for a, b in itertools.combinations(selected, 2):
                    if time.monotonic() >= deadline:
                        return {}
                    pair = a | b
                    if not any(child & pair == pair for child in child_masks):
                        best[pair] = None if pair in best else sha
            for parent in parents:
                masks[parent] = masks.get(parent, 0) | mask
                children.setdefault(parent, set()).add(mask)
        return best if time.monotonic() < deadline else {}

    def unique(self, a, b):
        if self.best is None:
            self.best = self._build()
        return self.best.get(self.bits.get(a, 0) | self.bits.get(b, 0))


def pair_merges(repo, commits):
    """Provide ordered independent pair merges with a serial fallback."""
    return _PairMerges(repo, commits)


def pair_bases(repo, commits):
    """Provide proven unique pair bases, or None for a scalar Git query."""
    return _PairBases(repo, commits)


def ancestor_relations(repo, commits):
    """Find ancestry between all selected commits with one history traversal."""
    if not commits:
        return set()
    bits = {sha: 1 << i for i, sha in enumerate(dict.fromkeys(commits))}
    masks = {}
    relations = set()
    result = _run(repo, 'rev-list', '--topo-order', '--reverse', '--parents', *bits)
    for line in result.stdout.decode('ascii').splitlines():
        sha, *parents = line.split()
        inherited = 0
        for parent in parents:
            inherited |= masks.get(parent, 0)
        if sha in bits:
            relations.update((ancestor, sha) for ancestor, bit in bits.items() if inherited & bit)
        masks[sha] = inherited | bits.get(sha, 0)
    return relations
