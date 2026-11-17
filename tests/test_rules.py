"""PLAN §6/§10: rules exercised only through engine.analyze()."""

import inspect

import pytest


API = "def charge(amount, currency):\n    return amount\n"


def test_cw001_demo_rename_and_new_call_into_untouched_module(repo, findings):
    repo.pair(
        {"billing.py": API},
        {"billing.py": API.replace("charge", "create_charge")},
        {"refunds.py": "import billing\nbilling.charge(1, 'USD')\n"},
        names=("rename-charge", "add-refunds"),
    )
    report = repo.analyze(("rename-charge", "add-refunds"))
    hits = findings(report, "CW001")
    assert len(hits) == 1
    hit = hits[0]
    assert (hit.branch, hit.other_branch, hit.path, hit.line, hit.symbol) == (
        "add-refunds", "rename-charge", "refunds.py", 2, "billing.charge",
    )
    assert hit.severity == "error"
    assert "removed in rename-charge" in hit.message
    assert "renamed to `billing.create_charge`?" in hit.message
    assert findings(report, "CW005") == []


@pytest.mark.parametrize("remove_module", [False, True])
def test_cw001_removed_symbol_or_module(repo, findings, remove_module):
    repo.pair(
        {"billing.py": API},
        {"billing.py": None if remove_module else "# API removed\n"},
        {"client.py": "from billing import charge as pay\npay(1, 'USD')\n"},
    )
    hits = findings(repo.analyze(), "CW001")
    assert hits
    assert all(h.symbol == "billing.charge" and h.branch == "b" for h in hits)


def test_cw001_renamed_file_removes_old_module(repo, findings):
    repo.pair(
        {"billing.py": API},
        {"billing.py": None, "payments.py": API},
        {"client.py": "import billing\nbilling.charge(1, 'USD')\n"},
    )
    assert findings(repo.analyze(), "CW001")


def test_cw001_runs_both_directions(repo, findings):
    repo.pair(
        {"one.py": "def f(): pass\n", "two.py": "def g(): pass\n"},
        {"one.py": "", "uses_two.py": "from two import g\ng()\n"},
        {"two.py": "", "uses_one.py": "from one import f\nf()\n"},
    )
    hits = findings(repo.analyze(), "CW001")
    assert {(h.branch, h.other_branch) for h in hits} == {("a", "b"), ("b", "a")}


def test_cw001_unchanged_references_and_shifted_lines_are_ignored(repo, findings):
    client = "import billing\nbilling.charge(1, 'USD')\n"
    repo.pair(
        {"billing.py": API, "client.py": client},
        {"billing.py": ""},
        {"client.py": "# extra documentation\n\n" + client},
    )
    assert findings(repo.analyze(), "CW001") == []


def test_cw001_repeated_identical_added_call_is_not_lost(repo, findings):
    client = "import billing\nbilling.charge(1, 'USD')\n"
    repo.pair(
        {"billing.py": API, "client.py": client},
        {"billing.py": ""},
        {"client.py": client + "billing.charge(1, 'USD')\n"},
    )
    hits = findings(repo.analyze(), "CW001")
    assert [(h.path, h.line) for h in hits] == [("client.py", 3)]


def test_cw001_own_redefinition_suppresses_stale_reference(repo, findings):
    repo.pair(
        {"billing.py": API},
        {"billing.py": ""},
        {"billing.py": API.replace("return amount", "return amount * 2"),
         "client.py": "import billing\nbilling.charge(1, 'USD')\n"},
    )
    assert findings(repo.analyze(textual=False), "CW001") == []


@pytest.mark.parametrize("client", [
    "from billing import *\ncharge(1, 'USD')\n",
    "import billing as bill\nbill = object()\nbill.charge(1, 'USD')\n",
    "import billing\ngetattr(billing, 'charge')(1, 'USD')\n",
])
def test_cw001_uncertain_targets_are_skipped(repo, findings, client):
    repo.pair({"billing.py": API}, {"billing.py": ""}, {"client.py": client})
    assert findings(repo.analyze(), "CW001") == []


SIGNATURE_CASES = [
    ("x", "x, y", "f(1)", True),
    ("x, y=0", "x", "f(1, y=2)", True),
    ("x, y=0", "x", "f(1, 2)", True),
    ("y, x=0", "x, y=0", "f(1, x=2)", True),
    ("x", "x, /", "f(x=1)", True),
    ("x", "x, *, required", "f(1)", True),
    ("**kwargs", "x, /, **kwargs", "f(x=1)", True),
    ("x", "x, y=0", "f(1)", False),
    ("x", "x, *args", "f(1)", False),
    ("x, y=0", "x, **kwargs", "f(1, y=2)", False),
    ("x, /, **kwargs", "x, /, **kwargs", "f(1, x=2)", False),
    ("x", "x, y", "f()", False),  # invalid at base too
    ("x", "x, y", "f(1, unknown=2)", False),
    ("x", "x, y", "f(*args)", False),
    ("x", "x, y", "f(1, **kwargs)", False),
    ("x", "x, y", "f(1, *args, **kwargs)", False),
]


@pytest.mark.parametrize(("old", "new", "call", "expected"), SIGNATURE_CASES)
def test_cw002_python_binding_matrix(repo, findings, old, new, call, expected):
    repo.pair(
        {"api.py": f"def f({old}): pass\n"},
        {"api.py": f"def f({new}): pass\n"},
        {"client.py": "from api import f\n" + call + "\n"},
    )
    hits = findings(repo.analyze(), "CW002")
    assert bool(hits) is expected
    if expected:
        assert len(hits) == 1
        assert (hits[0].symbol, hits[0].line, hits[0].branch) == ("api.f", 2, "b")
        assert hits[0].message and hits[0].severity == "error"


@pytest.mark.parametrize(("old", "new", "args", "kwargs"), [
    ("x", "x, y", (1,), {}),
    ("x, y=0", "x", (1,), {"y": 2}),
    ("x, y=0", "x", (1, 2), {}),
    ("y, x=0", "x, y=0", (1,), {"x": 2}),
    ("x", "x, /", (), {"x": 1}),
    ("x", "x, *, required", (1,), {}),
])
def test_binding_positive_fixtures_match_python_oracle(old, new, args, kwargs):
    namespace = {}
    exec(f"def old({old}): pass\ndef new({new}): pass\n", namespace)
    inspect.signature(namespace["old"]).bind(*args, **kwargs)
    with pytest.raises(TypeError):
        inspect.signature(namespace["new"]).bind(*args, **kwargs)


def test_cw002_plain_constructor(repo, findings):
    repo.pair(
        {"api.py": "class Client:\n    def __init__(self, host): pass\n"},
        {"api.py": "class Client:\n    def __init__(self, host, token): pass\n"},
        {"client.py": "from api import Client\nClient('localhost')\n"},
    )
    assert len(findings(repo.analyze(), "CW002")) == 1


def test_cw002_decorated_function_is_not_checked(repo, findings):
    repo.pair(
        {"api.py": "@decorate\ndef f(x): pass\n"},
        {"api.py": "@decorate\ndef f(x, y): pass\n"},
        {"client.py": "from api import f\nf(1)\n"},
    )
    assert findings(repo.analyze(), "CW002") == []


def test_cw002_existing_call_shifted_in_file_is_ignored(repo, findings):
    client = "from api import f\nf(1)\n"
    repo.pair(
        {"api.py": "def f(x): pass\n", "client.py": client},
        {"api.py": "def f(x, y): pass\n"},
        {"client.py": "# documentation\n" + client},
    )
    assert findings(repo.analyze(), "CW002") == []


@pytest.mark.parametrize("branches", [("a", "b"), ("b", "a")])
def test_cw003_duplicate_definition_once_with_lexical_location(repo, findings, branches):
    repo.pair({}, {"api.py": "def parse_config(): return 1\n"},
              {"api.py": "def parse_config(): return 2\n"})
    hits = findings(repo.analyze(branches, textual=False), "CW003")
    assert len(hits) == 1
    hit = hits[0]
    assert (hit.severity, hit.branch, hit.other_branch, hit.path, hit.line) == (
        "warning", "b", "a", "api.py", 1,
    )


def test_cw003_same_class_method_added(repo, findings):
    repo.pair(
        {"api.py": "class Client: pass\n"},
        {"api.py": "class Client:\n    def send(self): return 1\n"},
        {"api.py": "class Client:\n    def send(self): return 2\n"},
    )
    hits = findings(repo.analyze(textual=False), "CW003")
    assert len(hits) == 1
    assert hits[0].symbol.endswith("Client.send")


@pytest.mark.parametrize(("base", "left", "right"), [
    ({}, {"api.py": "def f(): return 1\n"}, {"api.py": "# comment\ndef f():\n    return 1\n"}),
    ({"api.py": "def f(): return 0\n"}, {"api.py": "def f(): return 1\n"}, {"api.py": "def f(): return 2\n"}),
    ({}, {"one.py": "def f(): return 1\n"}, {"two.py": "def f(): return 2\n"}),
    ({}, {"api.py": "class One:\n    def f(self): return 1\n"},
     {"api.py": "class Two:\n    def f(self): return 2\n"}),
])
def test_cw003_non_collisions(repo, findings, base, left, right):
    repo.pair(base, left, right)
    assert findings(repo.analyze(textual=False), "CW003") == []


def test_cw004_django_same_number_same_directory(repo, findings):
    repo.pair({}, {"app/migrations/0007_left.py": "# left\n"},
              {"app/migrations/0007_right.py": "# right\n"})
    hits = findings(repo.analyze(), "CW004")
    assert len(hits) == 1
    assert hits[0].severity == "error"


@pytest.mark.parametrize(("left", "right"), [
    ("app/migrations/0007_left.py", "app/migrations/0008_right.py"),
    ("one/migrations/0007_left.py", "two/migrations/0007_right.py"),
    ("app/migrations/007_left.py", "app/migrations/007_right.py"),
    ("app/0007_left.py", "app/0007_right.py"),
    ("app/migrations/0007_same.py", "app/migrations/0007_same.py"),
])
def test_cw004_django_non_collisions(repo, findings, left, right):
    repo.pair({}, {left: "# left\n"}, {right: "# right\n"})
    assert findings(repo.analyze(textual=False), "CW004") == []


@pytest.mark.parametrize(("left", "right"), [
    ("'parent'", "'parent'"),
    ("('other', 'parent')", "['parent', 'third']"),
    ("['parent']", "'parent'"),
])
def test_cw004_alembic_literal_intersection(repo, findings, left, right):
    repo.pair({}, {"alembic/versions/left.py": f"down_revision = {left}\n"},
              {"alembic/versions/right.py": f"down_revision = {right}\n"})
    assert len(findings(repo.analyze(), "CW004")) == 1


@pytest.mark.parametrize(("left", "right"), [
    ("None", "None"), ("''", "''"), ("'one'", "'two'"),
    ("compute()", "compute()"), ("['parent', dynamic]", "'parent'"),
])
def test_cw004_alembic_non_collisions(repo, findings, left, right):
    repo.pair({}, {"alembic/versions/left.py": f"down_revision = {left}\n"},
              {"alembic/versions/right.py": f"down_revision = {right}\n"})
    assert findings(repo.analyze(), "CW004") == []


def test_cw004_alembic_requires_versions_directory(repo, findings):
    repo.pair({}, {"ordinary/left.py": "down_revision = 'parent'\n"},
              {"ordinary/right.py": "down_revision = 'parent'\n"})
    assert findings(repo.analyze(), "CW004") == []


def test_cw004_only_new_migrations_collide(repo, findings):
    repo.pair(
        {"app/migrations/0007_old.py": "# old\n"},
        {"app/migrations/0007_old.py": "# modified\n"},
        {"app/migrations/0007_new.py": "# new\n"},
    )
    assert findings(repo.analyze(), "CW004") == []


def test_cw005_text_conflict_once_per_path(repo, findings):
    repo.pair({"readme.txt": "base\n"}, {"readme.txt": "left\n"}, {"readme.txt": "right\n"})
    hits = findings(repo.analyze(), "CW005")
    assert len(hits) == 1
    hit = hits[0]
    assert (hit.path, hit.line, hit.symbol, hit.branch, hit.other_branch) == (
        "readme.txt", 1, None, "b", "a",
    )
    assert hit.severity == "error"
    assert findings(repo.analyze(textual=False), "CW005") == []


def test_cw005_clean_merge_no_findings(repo, findings):
    repo.pair({}, {"left.txt": "left\n"}, {"right.txt": "right\n"})
    assert findings(repo.analyze(), "CW005") == []
