import pytest

from .helpers import RepoBuilder
from .golden_support import finish_recording


def pytest_sessionfinish(session, exitstatus):
    finish_recording()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    builder = RepoBuilder(tmp_path / "repository with spaces")
    # Public Git functions inherit the same isolated configuration as setup commands.
    for name, value in builder.env.items():
        if name.startswith("GIT_") or name == "LC_ALL":
            monkeypatch.setenv(name, value)
    yield builder


@pytest.fixture
def findings():
    return lambda report, rule: [f for f in report.findings if f.rule == rule]
