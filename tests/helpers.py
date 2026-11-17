"""Real, isolated Git fixtures; no commands operate on the project repository."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from contextlib import contextmanager


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class RepoBuilder:
    def __init__(self, path: Path):
        self.path = path
        self.path.mkdir(parents=True)
        hooks = path.parent / (path.name + "-empty-hooks")
        hooks.mkdir()
        self.env = dict(os.environ)
        self.env.update(
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_NOSYSTEM="1",
            GIT_OPTIONAL_LOCKS="0",
            LC_ALL="C",
            GIT_AUTHOR_NAME="Crosswire Tests",
            GIT_AUTHOR_EMAIL="tests@example.invalid",
            GIT_COMMITTER_NAME="Crosswire Tests",
            GIT_COMMITTER_EMAIL="tests@example.invalid",
            GIT_AUTHOR_DATE="2000-01-01T00:00:00+0000",
            GIT_COMMITTER_DATE="2000-01-01T00:00:00+0000",
        )
        self.git("init", "-b", "main")
        self.git("config", "core.hooksPath", str(hooks))
        self.git("config", "commit.gpgSign", "false")
        self.git("config", "core.autocrlf", "false")
        self.commit("initial")

    def git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args], cwd=self.path, env=self.env,
            capture_output=True, check=check,
        )

    def write(self, path: str, content: str | bytes):
        target = self.path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode() if isinstance(content, str) else content)
        return target

    def delete(self, path: str):
        (self.path / path).unlink()

    def rename(self, old: str, new: str):
        target = self.path / new
        target.parent.mkdir(parents=True, exist_ok=True)
        (self.path / old).rename(target)

    def commit(self, message: str = "change") -> str:
        self.git("add", "-A")
        self.git("commit", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD").stdout.decode().strip()

    def branch(self, name: str, start: str = "HEAD"):
        self.git("branch", name, start)

    def checkout(self, name: str):
        self.git("checkout", name)

    def apply(self, files: dict[str, str | bytes | None]):
        for path, source in files.items():
            if source is None:
                self.delete(path)
            else:
                self.write(path, source)

    def pair(self, base, left, right, names=("a", "b")) -> str:
        self.apply(base)
        base_sha = self.commit("base")
        for name, changes in zip(names, (left, right), strict=True):
            self.branch(name, base_sha)
            self.checkout(name)
            self.apply(changes)
            self.commit(name)
        return base_sha

    def snapshot(self):
        # Read bytes rather than `git status`, which can refresh the index.
        files = {}
        for root, dirs, names in os.walk(self.path):
            if Path(root) == self.path:
                dirs[:] = [d for d in dirs if d != ".git"]
            for name in names:
                path = Path(root) / name
                files[str(path.relative_to(self.path))] = (
                    ("symlink", os.readlink(path)) if path.is_symlink()
                    else ("file", path.read_bytes(), path.stat().st_mode)
                )
        index = self.path / ".git" / "index"
        return (
            self.git("rev-parse", "HEAD").stdout,
            self.git("symbolic-ref", "-q", "HEAD", check=False).stdout,
            self.git("show-ref", check=False).stdout,
            index.read_bytes() if index.exists() else None,
            files,
        )

    @contextmanager
    def unchanged(self):
        before = self.snapshot()
        try:
            yield
        finally:
            assert self.snapshot() == before, "Analysis changed HEAD, refs, index or worktree (PLAN §0/§9)"

    def analyze(self, branches=("a", "b"), **kwargs):
        from crosswire.engine import analyze
        from .golden_support import capture_report, enabled_for_case

        with self.unchanged():
            report = analyze(self.path, list(branches), **kwargs)
        capture_report(report)
        if enabled_for_case():
            args = ["--format", "json"]
            if kwargs.get("base") is not None:
                args.extend(["--base", kwargs["base"]])
            if kwargs.get("textual") is False:
                args.append("--no-textual")
            for root in kwargs.get("src") or []:
                args.extend(["--src", root])
            self.check(*args, branches=branches)
        return report

    def cli(self, *args: str, cwd: Path | None = None):
        env = dict(self.env)
        source = os.environ.get("CROSSWIRE_GOLDEN_SOURCE", str(PROJECT_ROOT / "src"))
        env["PYTHONPATH"] = source + os.pathsep + env.get("PYTHONPATH", "")
        with self.unchanged():
            result = subprocess.run(
                [sys.executable, "-m", "crosswire", *args],
                cwd=cwd or self.path.parent, env=env, capture_output=True, text=True,
            )
        if result.returncode in (0, 1) and args and args[0] == "check":
            from .golden_support import capture
            capture("cli", {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
        return result

    def check(self, *args: str, branches=("a", "b"), cwd: Path | None = None):
        return self.cli("check", "--repo", str(self.path), *args, *branches, cwd=cwd)
