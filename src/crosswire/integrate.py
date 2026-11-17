"""Integrate branches into deterministic, unreferenced virtual commits."""

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .git import GitError


@dataclass(frozen=True, slots=True)
class Integration:
    """The final virtual commit and the branches accepted or skipped."""

    commit: str
    integrated: tuple[str, ...]
    skipped: tuple[tuple[str, tuple[str, ...]], ...]


_memo = {}


def _run(repo, args, *, data=None):
    env = os.environ.copy()
    env.update({
        'LC_ALL': 'C', 'GIT_OPTIONAL_LOCKS': '0',
        'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
        'GIT_AUTHOR_NAME': 'crosswire', 'GIT_AUTHOR_EMAIL': 'crosswire@invalid',
        'GIT_COMMITTER_NAME': 'crosswire', 'GIT_COMMITTER_EMAIL': 'crosswire@invalid',
        'GIT_AUTHOR_DATE': '@0 +0000', 'GIT_COMMITTER_DATE': '@0 +0000',
    })
    try:
        return subprocess.run(['git', *args], cwd=repo, env=env,
                              input=data, capture_output=True)
    except OSError as exc:
        raise GitError(str(exc)) from exc


def _merge(repo, previous, branch):
    key = (str(Path(repo).resolve()), previous, branch)
    if key in _memo:
        return _memo[key]
    result = _run(repo, ['merge-tree', '--write-tree', '--name-only', '-z',
                         '--no-messages', previous, branch])
    parts = result.stdout.split(b'\0')
    if result.returncode not in (0, 1) or not re.fullmatch(rb'(?:[0-9a-f]{40}|[0-9a-f]{64})', parts[0]):
        raise GitError(result.stderr.decode('utf-8', 'replace').strip() or 'git merge-tree failed')
    if result.returncode == 1:
        outcome = (None, tuple(sorted({os.fsdecode(path) for path in parts[1:] if path})))
    else:
        tree = parts[0].decode('ascii')
        commit = _run(repo, ['-c', 'commit.gpgSign=false', 'commit-tree', tree,
                             '-p', previous, '-p', branch], data=b'crosswire virtual merge\n')
        if commit.returncode:
            raise GitError(commit.stderr.decode('utf-8', 'replace').strip() or 'git commit-tree failed')
        outcome = (commit.stdout.decode('ascii').strip(), ())
    _memo[key] = outcome
    return outcome


def integrate(repo, target_sha: str, branches: Sequence[tuple[str, str]]) -> Integration:
    """Merge branches in order, skipping conflicting branches without changing refs."""
    current = target_sha
    integrated = []
    skipped = []
    for label, branch in branches:
        commit, paths = _merge(repo, current, branch)
        if commit is None:
            skipped.append((label, paths))
        else:
            current = commit
            integrated.append(label)
    return Integration(current, tuple(integrated), tuple(skipped))
