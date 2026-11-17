import atexit
import os
import re
import subprocess
import threading
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal


class GitError(Exception):
    pass


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
    return Path(os.fsdecode(
        _run(path, 'rev-parse', '--show-toplevel').stdout.rstrip(b'\n')))


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
    return version


def resolve(repo, ref):
    """Resolve a user revision to a commit or report an unknown revision."""
    result = _run(repo, 'rev-parse', '--verify', '--end-of-options',
                  f'{ref}^{{commit}}', allowed=(0, 1, 128))
    if result.returncode:
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
            self.process = subprocess.Popen(['git', 'cat-file', '--batch', '-z'], cwd=repo,
                                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=subprocess.DEVNULL, env=env)
        except OSError as exc:
            raise GitError(str(exc)) from exc
        self.lock = threading.Lock()

    def read(self, rev, path):
        request = os.fsencode(f'{rev}:{path}')
        if b'\0' in request:
            raise GitError('NUL in Git object path')
        with self.lock:
            try:
                self.process.stdin.write(request + b'\0')
                self.process.stdin.flush()
                header = self.process.stdout.readline()
                match = re.fullmatch(rb'[0-9a-fA-F]{40,64} ([a-z]+) ([0-9]+)\n', header)
                if match:
                    kind, size = match.group(1), int(match.group(2))
                    content = self.process.stdout.read(size)
                    end = self.process.stdout.read(1)
                    if len(content) != size or end != b'\n':
                        raise GitError('truncated git cat-file response')
                    if kind != b'blob':
                        raise GitError(f'not a blob: {path}')
                    return content.decode('utf-8', 'replace')
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


@lru_cache(maxsize=16384)
def _read_file_sha(repo, rev, path):
    return _read_batch(repo, rev, path)


def read_file(repo, rev, path):
    """Read a Git blob with a shared batch process; missing paths return None."""
    if re.fullmatch(r'(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})', rev):
        return _read_file_sha(str(repo), rev, path)
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
