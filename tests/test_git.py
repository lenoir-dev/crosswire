"""PLAN §2: public Git functions, real repositories and unusual path names."""

from pathlib import Path
import shlex
import shutil
import subprocess

import pytest

from crosswire.git import (
    GitError, SkippedBlob, changed_files, git_version, is_ancestor, list_files, merge_base,
    merge_tree_conflicts, read_file, repo_root, resolve,
)


def test_repo_root_resolve_and_version(repo):
    nested = repo.path / "nested" / "directory"
    nested.mkdir(parents=True)
    with repo.unchanged():
        assert repo_root(nested) == repo.path
        sha = resolve(repo.path, "main")
        assert len(sha) in (40, 64)
        assert int(sha, 16) >= 0
        assert resolve(repo.path, sha) == sha
        assert git_version(repo.path) >= (2, 38, 0)


@pytest.mark.parametrize("ref", ["does-not-exist", "--help", "HEAD:not-a-commit"])
def test_invalid_ref_raises_git_error(repo, ref):
    with repo.unchanged(), pytest.raises(GitError):
        resolve(repo.path, ref)


def test_merge_base_and_ancestry(repo):
    base = repo.pair({}, {"a.txt": "a"}, {"b.txt": "b"})
    with repo.unchanged():
        assert merge_base(repo.path, "a", "b") == base
        assert is_ancestor(repo.path, base, "a") is True
        assert is_ancestor(repo.path, "a", "b") is False


def test_no_merge_base_returns_none(repo):
    repo.branch("old")
    repo.git("checkout", "--orphan", "unrelated")
    repo.write("other", "other")
    repo.commit("unrelated")
    with repo.unchanged():
        assert merge_base(repo.path, "old", "unrelated") is None
        assert is_ancestor(repo.path, "old", "unrelated") is False


def test_changed_files_add_modify_delete_and_exact_rename(repo):
    repo.apply({"modify.py": "old\n", "delete.py": "delete\n", "before.py": "def unique(): return 4\n"})
    base = repo.commit("before")
    repo.apply({"modify.py": "new\n", "delete.py": None, "added.py": "new file\n"})
    repo.rename("before.py", "after.py")
    tip = repo.commit("after")
    with repo.unchanged():
        changes = changed_files(repo.path, base, tip)
    actual = {(c.status, c.path, c.old_path) for c in changes}
    assert actual == {
        ("A", "added.py", None), ("M", "modify.py", None),
        ("D", "delete.py", None), ("R", "after.py", "before.py"),
    }


def test_nul_delimited_paths_and_utf8_replacement(repo):
    base = repo.git("rev-parse", "HEAD").stdout.decode().strip()
    paths = ["space name.py", "tabs\there.py", "line\nbreak.py", "юникод.py"]
    for path in paths:
        repo.write(path, b"# bad byte: \xff\n")
    tip = repo.commit("unusual paths")
    with repo.unchanged():
        assert {c.path for c in changed_files(repo.path, base, tip)} == set(paths)
        assert set(list_files(repo.path, tip)) == set(paths)
        with pytest.raises(SkippedBlob) as skipped:
            read_file(repo.path, tip, paths[0])
        assert skipped.value.reason == "non-utf8"


def test_read_file_is_revision_specific_and_missing_is_none(repo):
    repo.write("api.py", "old\n")
    old = repo.commit("old")
    repo.write("api.py", "new\n")
    new = repo.commit("new")
    with repo.unchanged():
        assert read_file(repo.path, old, "api.py") == "old\n"
        assert read_file(repo.path, new, "api.py") == "new\n"
        assert read_file(repo.path, old, "api.py") == "old\n"
        assert read_file(repo.path, new, "missing.py") is None


def test_list_files_prefix(repo):
    repo.apply({"pkg/a.py": "", "pkg/b.txt": "", "other.py": ""})
    sha = repo.commit("files")
    with repo.unchanged():
        assert set(list_files(repo.path, sha, prefix="pkg/")) == {"pkg/a.py", "pkg/b.txt"}


def test_type_change_maps_to_modified(repo):
    repo.write("type.py", "ordinary file")
    base = repo.commit("regular")
    repo.delete("type.py")
    (repo.path / "type.py").symlink_to("target.py")
    tip = repo.commit("symlink")
    with repo.unchanged():
        changes = changed_files(repo.path, base, tip)
    assert [(c.status, c.path) for c in changes] == [("M", "type.py")]


def test_merge_tree_clean(repo):
    repo.pair({}, {"a.txt": "a\n"}, {"b.txt": "b\n"})
    with repo.unchanged():
        assert merge_tree_conflicts(repo.path, "a", "b") == []


def test_merge_tree_conflict_paths_are_sorted_unique(repo):
    repo.pair(
        {"z conflict.txt": "base\n", "a.txt": "base\n"},
        {"z conflict.txt": "left\n", "a.txt": "left\n"},
        {"z conflict.txt": "right\n", "a.txt": "right\n"},
    )
    with repo.unchanged():
        assert merge_tree_conflicts(repo.path, "a", "b") == ["a.txt", "z conflict.txt"]


def test_merge_tree_invalid_ref_is_not_an_empty_conflict_list(repo):
    with repo.unchanged(), pytest.raises(GitError):
        merge_tree_conflicts(repo.path, "main", "missing-ref")


def test_git_subprocess_contract(repo, monkeypatch):
    observed = []
    original = subprocess.run

    def record(*args, **kwargs):
        observed.append((args, kwargs))
        return original(*args, **kwargs)

    with repo.unchanged():
        with monkeypatch.context() as patch:
            patch.setattr(subprocess, "run", record)
            resolve(repo.path, "main")
    assert observed
    for args, kwargs in observed:
        assert isinstance(args[0], list)
        assert not kwargs.get("shell", False)
        assert Path(kwargs["cwd"]) == repo.path
        assert kwargs.get("capture_output") is True
        assert kwargs["env"]["GIT_OPTIONAL_LOCKS"] == "0"
        assert kwargs["env"]["LC_ALL"] == "C"


def test_old_git_is_git_error_and_cli_exit_two(repo, tmp_path, monkeypatch):
    repo.pair({}, {"a.txt": "a"}, {"b.txt": "b"})
    real_git = shutil.which("git")
    assert real_git
    directory = tmp_path / "fake-bin"
    directory.mkdir()
    executable = directory / "git"
    executable.write_text(
        '#!/bin/sh\nif [ "$1" = "--version" ]; then\n'
        '  printf "git version 2.37.0\\n"\nelse\n'
        f'  exec {shlex.quote(real_git)} "$@"\nfi\n'
    )
    executable.chmod(0o755)
    path = str(directory) + ":" + repo.env["PATH"]
    monkeypatch.setenv("PATH", path)
    repo.env["PATH"] = path
    with repo.unchanged(), pytest.raises(GitError):
        git_version(repo.path)
    result = repo.check()
    assert result.returncode == 2
    assert result.stdout == ""
    assert "crosswire: error: " in result.stderr
