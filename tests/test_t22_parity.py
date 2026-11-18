"""Pre-T22 behavior contracts; these pass against the frozen serial source.

No expectations are recorded from a candidate. Native Git supplies the scalar
merge-base oracle where Git deliberately leaves a multiple-base choice open.
"""

import itertools
import json
import os
import shutil
import subprocess
import sys

import pytest

from crosswire import git
from crosswire.engine import analyze

from .helpers import PROJECT_ROOT


def _protected_git(repo):
    """Include config/reflogs/modes as well as RepoBuilder's HEAD/index/refs."""
    directory = repo.path / ".git"
    result = {}
    for root, dirs, names in os.walk(directory):
        if root == str(directory):
            dirs[:] = [name for name in dirs if name not in {"objects", "crosswire"}]
        for name in names:
            path = os.path.join(root, name)
            relative = os.path.relpath(path, directory)
            if os.path.islink(path):
                result[relative] = (os.lstat(path).st_mode, os.readlink(path))
            else:
                with open(path, "rb") as stream:
                    result[relative] = (os.stat(path).st_mode, stream.read())
    return result


def _check(repo, branches, *options):
    env = dict(repo.env, PYTHONPATH=str(PROJECT_ROOT / "src"), PYTHONDONTWRITEBYTECODE="1")
    before = _protected_git(repo)
    with repo.unchanged():
        result = subprocess.run(
            [sys.executable, "-B", "-m", "crosswire", "check", "--repo", ".",
             *options, *branches],
            cwd=repo.path, env=env, capture_output=True,
        )
    assert _protected_git(repo) == before
    return result.returncode, result.stdout, result.stderr


@pytest.mark.parametrize(("branches", "options", "message"), [
    (("missing",), (), "at least two branches are required"),
    (("a", "a", "missing"), (), "unknown revision: missing"),
    (("a", "alias"), ("--base", "missing-base"), "branches must resolve to distinct commits"),
    (("a", "missing"), ("--base", "missing-base"), "unknown revision: missing"),
    (("a", "b"), ("--base", "missing-base"), "unknown revision: missing-base"),
    (("a", "b"), ("--target", "missing-target"), "unknown revision: missing-target"),
    (("a", "b"), ("--base", "a"), "base is not an ancestor of both a and b"),
])
def test_validation_error_precedence(repo, branches, options, message):
    repo.pair({}, {"a_bad.py": "def a(\n"}, {"b_bad.py": "def b(\n"})
    repo.branch("alias", "a")
    assert _check(repo, branches, *options) == (
        2, b"", f"crosswire: error: {message}\n".encode(),
    )


@pytest.mark.parametrize("late_failure", [False, True])
def test_pair_base_error_retains_only_preceding_parse_warnings(repo, late_failure):
    commits = repo.named_dag({}, {
        "a": ("target", {"a_bad.py": "def a(\n"}),
        "b": ("target", {"b_bad.py": "def b(\n"}),
    })
    tree = repo.git("rev-parse", "b^{tree}").stdout.decode().strip()
    unrelated = repo.git("commit-tree", tree, "-m", "unrelated root").stdout.decode().strip()
    repo.git("update-ref", "refs/heads/unrelated", unrelated)
    branches = ("a", "b", "unrelated") if late_failure else ("a", "unrelated", "b")
    warnings = b"".join(
        f"crosswire: warning: cannot parse {label}_bad.py@{commits[label][:7]}\n".encode()
        for label in ("a", "b")
    ) if late_failure else b""
    assert _check(repo, branches, "--no-cache") == (
        2, b"", warnings + b"crosswire: error: no merge base for a and unrelated\n",
    )


def _fail_merge_pair(repo, tmp_path, monkeypatch, pair):
    """A Git executable fault works for serial, stdin and persistent callers.

    Self-merge capability probes still reach real Git. A speculative chunk
    containing the failed pair gets fatal stderr and must be replayed serially.
    """
    real_git = shutil.which("git")
    assert real_git
    directory = tmp_path / "git-fault"
    directory.mkdir()
    executable = directory / "git"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import os, subprocess, sys\n"
        f"real_git = {real_git!r}\n"
        f"failed_pair = {pair!r}\n"
        "args = sys.argv[1:]\n"
        "data = None\n"
        "failed = False\n"
        "if 'merge-tree' in args:\n"
        "    if '--stdin' in args:\n"
        "        data = sys.stdin.buffer.read()\n"
        "        failed = any(tuple(line.decode('ascii').split()) == failed_pair\n"
        "                     for line in data.splitlines())\n"
        "    else:\n"
        "        failed = tuple(args[-2:]) == failed_pair\n"
        "if failed:\n"
        "    sys.stderr.buffer.write(b'fatal: injected pair merge failure\\n')\n"
        "    sys.exit(128)\n"
        "if data is None:\n"
        "    os.execv(real_git, [real_git, *args])\n"
        "result = subprocess.run([real_git, *args], input=data, capture_output=True)\n"
        "sys.stdout.buffer.write(result.stdout)\n"
        "sys.stderr.buffer.write(result.stderr)\n"
        "sys.exit(result.returncode)\n"
    )
    executable.chmod(0o755)
    path = str(directory) + os.pathsep + repo.env["PATH"]
    repo.env["PATH"] = path
    monkeypatch.setenv("PATH", path)


@pytest.mark.parametrize("failure_pair", [("a", "b"), ("a", "c")])
def test_merge_error_follows_that_pairs_summaries(repo, tmp_path, monkeypatch, failure_pair):
    commits = repo.named_dag({}, {
        label: ("target", {f"{label}_bad.py": f"def {label}(\n"})
        for label in ("a", "b", "c")
    })
    _fail_merge_pair(repo, tmp_path, monkeypatch, tuple(commits[label] for label in failure_pair))
    warned = ("a", "b") if failure_pair == ("a", "b") else ("a", "b", "c")
    expected = b"".join(
        f"crosswire: warning: cannot parse {label}_bad.py@{commits[label][:7]}\n".encode()
        for label in warned
    ) + b"crosswire: error: fatal: injected pair merge failure\n"
    assert _check(repo, ("a", "b", "c"), "--no-cache") == (2, b"", expected)


@pytest.mark.parametrize("textual", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
def test_mixed_pair_results_preserve_pair_and_finding_order(repo, textual, reverse):
    commits = repo.named_dag({"shared.txt": "base\n"}, {
        "z-left": ("target", {"shared.txt": "left\n"}),
        "middle": ("target", {"independent.txt": "safe\n"}),
        "a-right": ("target", {"shared.txt": "right\n"}),
    })
    branches = ("z-left", "middle", "a-right")
    if reverse:
        branches = branches[::-1]
    options = () if textual else ("--no-textual",)
    actual = _check(repo, branches, "--format", "json", *options)
    findings = [{
        "rule": "CW005", "severity": "error", "message": "textual conflict with a-right",
        "branch": "z-left", "other_branch": "a-right", "path": "shared.txt", "line": 1,
        "symbol": None, "hint": "rebase z-left onto a-right",
        "limitations": ["file-level location; conflict line unavailable"],
    }] if textual else []
    expected = {
        "version": 1, "tool": "crosswire", "coverage": "complete", "limitations": {},
        "pairs": [{"a": a, "b": b, "base": commits["target"]}
                  for a, b in itertools.combinations(branches, 2)],
        "findings": findings, "summary": {"errors": len(findings), "warnings": 0},
    }
    frozen_bytes = (json.dumps(expected, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode()
    assert actual == (int(textual), frozen_bytes, b"")
    # The second run also pins warm-cache bytes to the same literal expectation.
    assert _check(repo, branches, "--format", "json", *options) == actual


def test_conflict_filename_bytes_round_trip_without_line_splitting(repo):
    names = ["z space.txt", "line\nbreak\tname.txt", os.fsdecode(b"raw-\xff.txt")]
    # Git trees support byte names even on filesystems that reject non-UTF-8
    # working-tree names. Build the objects directly and leave HEAD untouched.
    def input_git(args, data):
        return subprocess.run(["git", *args], input=data, cwd=repo.path,
                              env=repo.env, capture_output=True, check=True).stdout.strip()

    base = None
    for label in ("base", "a", "b"):
        blob = input_git(["hash-object", "-w", "--stdin"], f"{label}\n".encode())
        tree = input_git(["mktree", "-z"], b"".join(
            b"100644 blob " + blob + b"\t" + os.fsencode(name) + b"\0" for name in names
        )).decode()
        parents = ["-p", base] if base is not None else []
        commit = repo.git("commit-tree", tree, *parents, "-m", label).stdout.decode().strip()
        if label == "base":
            base = commit
        else:
            repo.git("update-ref", f"refs/heads/{label}", commit)
    with repo.unchanged():
        assert git.merge_tree_conflicts(repo.path, "a", "b") == sorted(names)
        report = analyze(repo.path, ["a", "b"], cache=False)
    assert [(f.rule, os.fsencode(f.path)) for f in report.findings] == [
        ("CW005", os.fsencode(name)) for name in sorted(names)
    ]
    code, stdout, stderr = _check(repo, ("a", "b"), "--format", "json")
    assert (code, stderr) == (1, b"")
    assert [os.fsencode(f["path"]) for f in json.loads(stdout)["findings"]] == [
        os.fsencode(name) for name in sorted(names)
    ]
    assert b"\\udcff" in stdout


def test_criss_cross_preserves_each_native_scalar_orientation(repo):
    repo.pair({"shared.txt": "base\n"}, {"shared.txt": "left\n"},
              {"shared.txt": "right\n"}, names=("left-base", "right-base"))
    for label, parents in [("a", ("left-base", "right-base")),
                           ("b", ("right-base", "left-base"))]:
        tree = repo.git("rev-parse", f"{parents[0]}^{{tree}}").stdout.decode().strip()
        commit = repo.git("commit-tree", tree, "-p", parents[0], "-p", parents[1],
                          "-m", label).stdout.decode().strip()
        repo.git("update-ref", f"refs/heads/{label}", commit)
    all_bases = set(repo.git("merge-base", "--all", "a", "b").stdout.splitlines())
    assert len(all_bases) == 2
    for order in [("a", "b"), ("b", "a")]:
        # Ask native Git in precisely this orientation; --all/sorting cannot
        # define which base a scalar Git invocation would have selected.
        expected = repo.git("merge-base", *order).stdout.decode().strip()
        assert expected.encode() in all_bases
        with repo.unchanged():
            report = analyze(repo.path, list(order), cache=False)
        assert report.base_by_pair == {order: expected}
        code, stdout, stderr = _check(repo, order, "--format", "json")
        assert (code, stderr) == (1, b"")
        assert json.loads(stdout)["pairs"] == [{"a": order[0], "b": order[1], "base": expected}]


@pytest.mark.parametrize("detached", [False, True])
def test_pairwise_keeps_dirty_index_refs_config_logs_and_worktree(repo, detached):
    repo.named_dag({"shared.txt": "base\n"}, {
        "a": ("target", {"shared.txt": "left\n"}),
        "b": ("target", {"safe.txt": "safe\n"}),
        "c": ("target", {"shared.txt": "right\n"}),
    })
    if detached:
        repo.git("checkout", "--detach")
    repo.write("staged.txt", "staged\n")
    repo.git("add", "staged.txt")
    repo.write("staged.txt", "different unstaged bytes\n")
    repo.write("untracked.txt", b"untracked\x00bytes\n")
    executable = repo.write("executable.sh", "#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    (repo.path / "dirty-link").symlink_to("untracked.txt")
    config = repo.path / ".git" / "config"
    config.chmod(0o640)
    before = _protected_git(repo)
    with repo.unchanged():
        outputs = [_check(repo, ("a", "b", "c"), "--format", "json", *options)
                   for options in [("--no-cache",), (), ()]]
    assert outputs[0] == outputs[1] == outputs[2]
    assert (outputs[0][0], outputs[0][2]) == (1, b"")
    assert _protected_git(repo) == before
