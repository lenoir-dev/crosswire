"""Collect release-test fixture inputs, never production-derived expectations.

Loaded only in the isolated v0.4.0 pytest process by t21_equality.py.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import tarfile


class Collector:
    def __init__(self, output, fixture_root):
        self.output = Path(output)
        self.fixture_root = Path(fixture_root).resolve()
        self.states = {}
        self.tests = {}
        self.builders = []
        self.active = None
        self.originals = []

    def pytest_collection_modifyitems(self, items):
        self.tests = {item.nodeid: {"outcomes": {}, "fixtures": []} for item in items}

    def pytest_runtest_setup(self, item):
        self.active = item.nodeid

    def pytest_runtest_logreport(self, report):
        self.tests[report.nodeid]["outcomes"][report.when] = report.outcome

    def excluded(self, relative):
        parts = relative.parts
        return "__pycache__" in parts or any(
            parts[i:i + 2] == ("crosswire", "cache") for i in range(len(parts) - 1)
        )

    def archive_filter(self, info):
        """Keep fixture bytes/modes, omit host identity and wall-clock metadata."""
        if self.excluded(Path(info.name)):
            return None
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        info.mtime = 0
        # Extended headers override ordinary tar fields when present.
        for key in ("uid", "gid", "uname", "gname", "mtime", "atime", "ctime"):
            info.pax_headers.pop(key, None)
        return info

    def capture(self, builder):
        root = builder.path.parent.resolve()
        if not root.is_relative_to(self.fixture_root) or not root.exists():
            return None
        # Ignore object creation/cache writes when identifying the same input.
        # The archive still retains all Git objects needed to reconstruct it.
        digest = hashlib.sha256()
        entries = sorted(root.rglob("*"))
        for path in entries:
            relative = path.relative_to(root)
            if self.excluded(relative):
                continue
            if ".git" in relative.parts and any(p in {"objects", "logs"} for p in relative.parts):
                continue
            digest.update(relative.as_posix().encode() + b"\0")
            digest.update(str(path.lstat().st_mode).encode() + b"\0")
            if path.is_symlink():
                digest.update(os.readlink(path).encode())
            elif path.is_file():
                digest.update(path.read_bytes())
        identity = hashlib.sha256((str(root) + digest.hexdigest()).encode()).hexdigest()[:20]
        if identity not in self.states:
            archive = self.output / "fixtures" / (identity + ".tar.gz")
            archive.parent.mkdir(parents=True, exist_ok=True)
            with tarfile.open(archive, "w:gz", compresslevel=6) as stream:
                stream.add(root, arcname=".", filter=self.archive_filter)
            self.states[identity] = {
                "id": identity, "root": str(root), "repo": str(builder.path),
                "archive": str(archive.relative_to(self.output)),
                "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                "tests": [], "invocations": [],
            }
        state = self.states[identity]
        if self.active and self.active not in state["tests"]:
            state["tests"].append(self.active)
            self.tests[self.active]["fixtures"].append(identity)
        return state

    def install(self):
        from tests.helpers import RepoBuilder
        original_init = RepoBuilder.__init__
        original_unchanged = RepoBuilder.unchanged
        original_cli = RepoBuilder.cli
        owner = self

        def init(builder, *args, **kwargs):
            original_init(builder, *args, **kwargs)
            owner.builders.append(builder)

        @contextmanager
        def unchanged(builder):
            owner.capture(builder)
            with original_unchanged(builder):
                yield

        def cli(builder, *args, cwd=None):
            state = owner.capture(builder)
            if state is not None:
                entry = {"argv": list(args), "cwd": str(cwd or builder.path.parent)}
                # Only preserve a PATH override when a test deliberately installs
                # its fake Git. Ordinary developer PATHs never enter artifacts.
                if "fake-bin" in os.environ.get("PATH", ""):
                    entry["fake_git"] = os.environ["PATH"].split(os.pathsep)[0]
                if entry not in state["invocations"]:
                    state["invocations"].append(entry)
            return original_cli(builder, *args, cwd=cwd)

        for name, replacement in (("__init__", init), ("unchanged", unchanged), ("cli", cli)):
            self.originals.append((RepoBuilder, name, getattr(RepoBuilder, name)))
            setattr(RepoBuilder, name, replacement)

    def pytest_runtest_teardown(self, item):
        # Include fixtures used through direct APIs, including instrumented Vega
        # cases that never invoke RepoBuilder.cli()/unchanged().
        for builder in self.builders:
            if builder.path.exists():
                self.capture(builder)
        self.builders.clear()

    def pytest_sessionfinish(self, session, exitstatus):
        for cls, name, original in reversed(self.originals):
            setattr(cls, name, original)
        payload = {"exitstatus": int(exitstatus), "tests": self.tests, "fixtures": list(self.states.values())}
        (self.output / "inventory.json").write_text(json.dumps(payload, indent=2) + "\n")


def main():
    import sys
    import pytest
    output, root, baseline = map(Path, sys.argv[1:4])
    sys.path.insert(0, str(baseline))
    collector = Collector(output, root)
    collector.install()
    raise SystemExit(pytest.main(["-q", "--basetemp", str(root), "tests"], plugins=[collector]))


if __name__ == "__main__":
    main()
