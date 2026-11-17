import os
import re
import subprocess
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
        p = subprocess.run(['git', *args], cwd=repo, capture_output=True, env=env)
    except (OSError, ValueError) as e:
        raise GitError(str(e)) from e
    if p.returncode not in allowed:
        raise GitError(p.stderr.decode('utf-8', 'replace').strip() or f'git {args[0]} failed (exit {p.returncode})')
    return p

def repo_root(path):
    return Path(os.fsdecode(_run(path, 'rev-parse', '--show-toplevel').stdout.rstrip(b'\n')))

def git_version(repo):
    out = _run(repo, '--version').stdout.decode('ascii', 'replace')
    m = re.search(r'(\d+)\.(\d+)(?:\.(\d+))?', out)
    if not m:
        raise GitError('cannot determine git version')
    version = tuple(int(v or 0) for v in m.groups())
    if version < (2, 38, 0):
        raise GitError('Git 2.38 or newer is required')
    return version

def resolve(repo, ref):
    return _run(repo, 'rev-parse', '--verify', '--end-of-options', f'{ref}^{{commit}}').stdout.decode().strip()

def merge_base(repo, a, b):
    p = _run(repo, 'merge-base', a, b, allowed=(0, 1))
    return p.stdout.decode().strip() if p.returncode == 0 else None

def is_ancestor(repo, anc, desc):
    return _run(repo, 'merge-base', '--is-ancestor', anc, desc, allowed=(0, 1)).returncode == 0

def changed_files(repo, base, tip):
    parts = _run(repo, 'diff', '--name-status', '-z', '-M', base, tip, '--').stdout.split(b'\0')
    result = []
    i = 0
    while i < len(parts) and parts[i]:
        status = parts[i][:1].decode('ascii'); i += 1
        old = None
        if status in ('R', 'C'):
            old = os.fsdecode(parts[i]); i += 1
        path = os.fsdecode(parts[i]); i += 1
        if status == 'C': status, old = 'A', None
        if status == 'T': status = 'M'
        if status not in ('A', 'M', 'D', 'R'):
            raise GitError(f'unsupported diff status: {status}')
        result.append(FileChange(status, path, old))
    return result

@lru_cache(maxsize=16384)
def read_file(repo, rev, path):
    # Check existence separately so other git failures are not mistaken for missing files.
    p = _run(repo, 'cat-file', '-e', f'{rev}:{path}', allowed=(0, 1, 128))
    if p.returncode:
        return None
    return _run(repo, 'cat-file', 'blob', f'{rev}:{path}').stdout.decode('utf-8', 'replace')

def list_files(repo, rev, prefix=''):
    args = ['ls-tree', '-r', '-z', '--name-only', rev]
    if prefix:
        args += ['--', prefix]
    return [os.fsdecode(x) for x in _run(repo, *args).stdout.split(b'\0') if x]

def merge_tree_conflicts(repo, a, b):
    p = _run(repo, 'merge-tree', '--write-tree', '--name-only', '-z', '--no-messages', a, b, allowed=(0, 1))
    parts = p.stdout.split(b'\0')
    if not re.fullmatch(rb'(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})', parts[0]):
        raise GitError(p.stderr.decode('utf-8', 'replace').strip() or 'git merge-tree failed: invalid tree object ID')
    if p.returncode == 0:
        return []
    return sorted({os.fsdecode(x) for x in parts[1:] if x})
