"""Deterministic native Git fixture construction, independent of crosswire."""
import hashlib
import os
from pathlib import Path
import subprocess


def environment():
    env = {k:v for k,v in os.environ.items() if not k.startswith(("GIT_", "CROSSWIRE_", "PYTHONPATH"))}
    env.update(LC_ALL="C", LANG="C", TZ="UTC", GIT_OPTIONAL_LOCKS="0",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               GIT_AUTHOR_NAME="Conformance", GIT_AUTHOR_EMAIL="conformance@example.invalid",
               GIT_COMMITTER_NAME="Conformance", GIT_COMMITTER_EMAIL="conformance@example.invalid",
               GIT_AUTHOR_DATE="2000-01-01T00:00:00+0000", GIT_COMMITTER_DATE="2000-01-01T00:00:00+0000",
               PYTHONDONTWRITEBYTECODE="1")
    return env


def git(repo, *args, input=None, check=True):
    return subprocess.run(["git", *args], cwd=repo, env=environment(), input=input,
                          capture_output=True, check=check, timeout=60)


def write_files(repo, files):
    for relative, content in files.items():
        path = repo / relative
        if not path.resolve().is_relative_to(repo.resolve()):
            raise ValueError("Rendered path escapes repository")
        if content is None:
            path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)


def commit(repo, label):
    git(repo, "add", "--all")
    git(repo, "-c", "commit.gpgSign=false", "commit", "--quiet", "--allow-empty", "-m", label)
    return git(repo, "rev-parse", "HEAD").stdout.decode().strip()


def build(repo, rendered):
    repo.mkdir(parents=True)
    git(repo, "init", "--quiet", "-b", "main")
    git(repo, "config", "core.hooksPath", os.devnull)
    git(repo, "config", "core.autocrlf", "false")
    write_files(repo, rendered["base"])
    target = commit(repo, "target")
    tips = {}
    for branch in rendered["branches"]:
        git(repo, "checkout", "--quiet", "--detach", target)
        write_files(repo, branch["files"])
        tips[branch["id"]] = commit(repo, branch["id"])
        git(repo, "branch", branch["id"], tips[branch["id"]])
    git(repo, "checkout", "--quiet", "main")
    return target, tips


def integrate(repo, target, tips, labels):
    current = target
    for label in labels:
        merged = git(repo, "merge-tree", "--write-tree", current, tips[label], check=False)
        if merged.returncode != 0:
            raise ValueError("Template integration is textually conflicted: " + "+".join(labels))
        tree = merged.stdout.splitlines()[0].decode()
        current = git(repo, "-c", "commit.gpgSign=false", "commit-tree", tree,
                      "-p", current, "-p", tips[label], input=b"conformance integration\n").stdout.decode().strip()
    return current


def files_at(repo, revision):
    result = {}
    for path in git(repo, "ls-tree", "-r", "--name-only", "-z", revision).stdout.split(b"\0"):
        if path:
            relative = path.decode("utf-8")
            result[relative] = git(repo, "show", revision + ":" + relative).stdout
    return result


def snapshot(repo):
    # Ignore only unreferenced objects; no-cache subprocesses may not change any
    # other tracked, untracked, index, HEAD, ref or configuration bytes/modes.
    return {p.relative_to(repo).as_posix(): (p.stat().st_mode, hashlib.sha256(p.read_bytes()).hexdigest())
            for p in sorted(repo.rglob("*")) if p.is_file() and ".git/objects/" not in p.as_posix()}
