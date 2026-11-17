"""Seals bind tracked trees, refs, worktrees and the independent apparatus."""
import hashlib
import json
from pathlib import Path
import subprocess


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git(directory, *args):
    return subprocess.check_output(['git', *args], cwd=directory, env=__import__('os').environ | {'GIT_OPTIONAL_LOCKS':'0'}).decode().strip()


def assert_case(case):
    directory = Path(case['path'])
    assert git(directory, 'rev-parse', 'HEAD') == case['integrated'], 'Integrated HEAD changed'
    for branch, tip in case['tips'].items():
        assert git(directory, 'rev-parse', branch) == tip, 'Case tip changed'
    assert git(directory, 'diff', 'HEAD', '--') == '', 'Tracked worktree/index changed'
    assert not git(directory, 'ls-files', '--others', '--exclude-standard'), 'Untracked case files'
    if 'repository_sha256' in case:
        assert repository_hash(directory) == case['repository_sha256'], 'Repository state changed'


def repository_hash(directory):
    """Bind object graph, refs, index, modes, symlinks and every worktree file."""
    directory = Path(directory)
    h = hashlib.sha256()
    for p in sorted(directory.rglob('*')):
        if not (p.is_file() or p.is_symlink()):
            continue
        relative = p.relative_to(directory).as_posix()
        # Git operational metadata is deliberately included: final seal is immutable.
        content = p.readlink().as_posix().encode() if p.is_symlink() else p.read_bytes()
        h.update(relative.encode()+b'\0'+str(p.lstat().st_mode).encode()+b'\0'+content+b'\0')
    return h.hexdigest()


def apparatus(root):
    paths = sorted((root/'eval').rglob('*.py')) + [root/'eval/policy.json', root/'docs/validation/matching.md', root/'docs/validation/v04-oracle-requirements.txt',root/'eval/toolchain.json',root/'docs/validation/v04-oracle-requirements.lock']
    return {p.relative_to(root).as_posix(): digest(p) for p in paths}


def verify_seal(private, root, hash_list):
    lines = hash_list.read_text().splitlines()
    labels=[line.split('  ',1)[1] for line in lines]
    expected_labels={'private/manifest.json','private/repositories.json',*apparatus(root)}
    assert len(labels)==len(set(labels)) and set(labels)==expected_labels, 'Incomplete or duplicated seal hash list'
    for line in lines:
        expected, label = line.split('  ', 1)
        if label == 'private/manifest.json':
            assert digest(private/'manifest.json') == expected, 'Manifest seal changed'
        elif label == 'private/repositories.json':
            assert digest(private/'repositories.json') == expected, 'Repository list changed'
        else:
            assert digest(root/label) == expected, 'Apparatus seal changed'
    manifest = json.loads((private/'manifest.json').read_text())
    for case in manifest['cases']:
        assert_case(case)
    return manifest
