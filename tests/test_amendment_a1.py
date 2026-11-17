"""PLAN §11 (A1): re-exports and guarded module definitions are preserved APIs."""

import pytest

from crosswire.diffing import api_changes
from crosswire.python_analyzer import extract_symbols


@pytest.mark.parametrize(("source", "bound"), [
    ("from pkg.core.impl import charge\n", "charge"),
    ("from pkg.core.impl import charge as pay\n", "pay"),
    ("from .core.impl import charge\n", "charge"),
    ("import billing\n", "billing"),
    ("import pkg.core.impl\n", "pkg"),
    ("import pkg.core.impl as billing\n", "billing"),
])
def test_a1_module_imports_are_variable_definitions(source, bound):
    symbols = extract_symbols(source, "pkg.billing", "pkg/billing.py")
    assert set(symbols) == {bound}
    symbol = symbols[bound]
    assert symbol.qualname == bound
    assert symbol.kind == "variable"
    assert symbol.params is None
    assert symbol.module == "pkg.billing" and symbol.path == "pkg/billing.py"
    assert symbol.line == 1


def test_a1_star_import_does_not_define_symbols():
    assert extract_symbols("from pkg.core.impl import *\n", "pkg.billing", "pkg/billing.py") == {}


def test_a1_reexport_replaces_function_without_api_removal():
    before = extract_symbols("def charge(amount): return amount\n", "pkg.billing", "pkg/billing.py")
    after = extract_symbols("from pkg.core.impl import charge\n", "pkg.billing", "pkg/billing.py")
    assert api_changes(before, after) == []


@pytest.mark.parametrize("source", [
    "if enabled:\n    def helper(x): return x\nelse:\n    def helper(x, y): return x\n",
    "try:\n    def helper(x): return x\nexcept ImportError:\n    def helper(x, y): return x\n",
    "try:\n    from fast import helper\nexcept ImportError:\n    def helper(x): return x\n",
])
def test_a1_guarded_alternatives_have_unknown_signature(source):
    symbols = extract_symbols(source, "utils", "utils.py")
    assert "helper" in symbols
    assert symbols["helper"].params is None


@pytest.mark.parametrize(("source", "bound", "kind"), [
    ("if enabled:\n    flag = True\n", "flag", "variable"),
    ("if enabled:\n    pass\nelse:\n    flag: bool = False\n", "flag", "variable"),
    ("try:\n    flag = True\nexcept ImportError:\n    pass\n", "flag", "variable"),
    ("try:\n    pass\nexcept ImportError:\n    from fallback import helper\n", "helper", "variable"),
    ("try:\n    pass\nexcept ImportError:\n    pass\nelse:\n    flag = True\n", "flag", "variable"),
    ("try:\n    pass\nfinally:\n    import package as helper\n", "helper", "variable"),
    ("with context():\n    def helper(x): return x\n", "helper", "function"),
    ("if enabled:\n    with context():\n        try:\n            flag = True\n        finally:\n            pass\n", "flag", "variable"),
    ("if enabled:\n    class Client:\n        def send(self): pass\n", "Client.send", "method"),
])
def test_a1_all_guarded_module_blocks_are_traversed(source, bound, kind):
    symbols = extract_symbols(source, "utils", "utils.py")
    assert bound in symbols
    assert symbols[bound].kind == kind


def test_a1_function_local_bindings_do_not_become_module_definitions():
    symbols = extract_symbols(
        "def outer():\n"
        "    if enabled:\n"
        "        from pkg import local_import\n"
        "        local_assignment = 1\n"
        "        def local_function(): pass\n",
        "utils", "utils.py",
    )
    assert set(symbols) == {"outer"}


@pytest.mark.parametrize("replacement", [
    "from pkg.core.impl import charge\n",
    "from pkg.core.impl import charge as charge\n",
    "from .core.impl import charge\n",
    "import pkg.core.impl as charge\n",
])
def test_a1_cw001_reexport_or_module_alias_is_not_removal(repo, findings, replacement):
    repo.pair(
        {
            "pkg/__init__.py": "", "pkg/core/__init__.py": "",
            "pkg/core/impl.py": "def charge(amount): return amount\n",
            "pkg/billing.py": "def charge(amount): return amount\n",
        },
        {"pkg/billing.py": replacement},
        {"client.py": "from pkg.billing import charge\ncharge(10)\n"},
    )
    assert findings(repo.analyze(), "CW001") == []


@pytest.mark.parametrize("replacement", [
    "import sys\n"
    "if sys.version_info >= (3, 11):\n"
    "    def helper(value): return value\n"
    "else:\n"
    "    def helper(value): return value + 1\n",
    "try:\n"
    "    def helper(value): return value\n"
    "except ImportError:\n"
    "    def helper(value): return value + 1\n",
    "try:\n"
    "    from optional_helpers import helper\n"
    "except ImportError:\n"
    "    def helper(value): return value\n",
])
def test_a1_cw001_guarded_definition_is_not_removal(repo, findings, replacement):
    repo.pair(
        {"pkg/__init__.py": "", "pkg/utils.py": "def helper(value): return value\n"},
        {"pkg/utils.py": replacement},
        {"client.py": "from pkg.utils import helper\nhelper(10)\n"},
    )
    assert findings(repo.analyze(), "CW001") == []


def test_a1_cw001_actual_deletion_still_reports(repo, findings):
    repo.pair(
        {"pkg/__init__.py": "", "pkg/billing.py": "def charge(amount): return amount\n"},
        {"pkg/billing.py": "# charge was deleted; no replacement binding\n"},
        {"client.py": "from pkg.billing import charge\ncharge(10)\n"},
    )
    hits = findings(repo.analyze(), "CW001")
    assert hits
    assert all(hit.symbol == "pkg.billing.charge" for hit in hits)
    assert all(hit.branch == "b" and hit.other_branch == "a" for hit in hits)


def test_readme_demo_cli_reports_semantic_error_despite_clean_git_merge(repo):
    # Match README.md's Demo source, branch names, and operations in an isolated repo.
    repo.write("billing.py", "def charge(amount, currency):\n    return amount\n")
    repo.commit("base")
    repo.branch("rename-charge")
    repo.checkout("rename-charge")
    repo.write("billing.py", "def create_charge(amount, currency):\n    return amount\n")
    repo.commit("rename")
    repo.checkout("main")
    repo.branch("add-refunds")
    repo.checkout("add-refunds")
    repo.write(
        "refunds.py",
        'import billing\n\ndef refund():\n    return billing.charge(10, "USD")\n',
    )
    repo.commit("refunds")
    with repo.unchanged():
        merge = repo.git("merge-tree", "--write-tree", "rename-charge", "add-refunds", check=False)
    assert merge.returncode == 0, merge.stderr.decode()
    assert len(merge.stdout.decode().strip()) in (40, 64)
    result = repo.cli("check", "rename-charge", "add-refunds", cwd=repo.path)
    assert result.returncode == 1, result.stderr
    assert "CW001" in result.stdout
    assert "create_charge" in result.stdout
    assert "renamed to `billing.create_charge`?" in result.stdout
    assert "CW005" not in result.stdout
    assert result.stderr == ""
