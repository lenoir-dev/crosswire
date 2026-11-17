"""PLAN §3–4: extraction contracts, independent of Git and rule internals."""

import dataclasses

import pytest

from crosswire.model import CallShape, Param
from crosswire.python_analyzer import (
    extract_references, extract_symbols, module_name_for_path,
)


@pytest.mark.parametrize(("path", "roots", "expected"), [
    ("src/pkg/util.py", ["src", "."], "pkg.util"),
    ("src/pkg/util.py", [".", "src"], "src.pkg.util"),
    ("pkg/__init__.py", ["."], "pkg"),
    ("src/pkg/__init__.py", ["src"], "pkg"),
    ("pkg/mod.py", ["."], "pkg.mod"),
    ("source/mod.py", ["src"], None),
    ("src2/mod.py", ["src"], None),
    ("src/pkg/thing.txt", ["src"], None),
    ("src/bad-name.py", ["src"], None),
    ("src/123pkg/mod.py", ["src"], None),
    ("lib/mod.py", ["src", "lib"], "mod"),
    ("pkg/модуль.py", ["."], "pkg.модуль"),
])
def test_module_name_uses_ordered_component_roots(path, roots, expected):
    assert module_name_for_path(path, roots) == expected


def test_symbols_kinds_qualified_names_and_last_definition():
    source = (
        "value = 1\n"
        "label: str = 'x'\n"
        "def f(first):\n    def nested(): pass\n"
        "async def worker(x): pass\n"
        "class C:\n    def method(self, x): pass\n"
        "def f(last): pass\n"
    )
    symbols = extract_symbols(source, "pkg.api", "pkg/api.py")
    assert set(symbols) == {"value", "label", "f", "worker", "C", "C.method"}
    assert symbols["f"].line == 8
    assert symbols["f"].kind == "function"
    assert symbols["worker"].kind == "function"
    assert symbols["C"].kind == "class"
    assert symbols["C.method"].kind == "method"
    assert symbols["C.method"].params is None
    assert symbols["value"].params is None
    assert symbols["label"].kind == "variable"
    assert all(s.module == "pkg.api" and s.path == "pkg/api.py" for s in symbols.values())


def test_all_parameter_kinds_and_defaults():
    symbols = extract_symbols(
        "def f(a, b=1, /, c=2, *args, d, e=3, **kwargs): pass\n",
        "api", "api.py",
    )
    assert symbols["f"].params == (
        Param("a", "posonly", False), Param("b", "posonly", True),
        Param("c", "pos", True), Param("args", "vararg", False),
        Param("d", "kwonly", False), Param("e", "kwonly", True),
        Param("kwargs", "varkw", False),
    )


@pytest.mark.parametrize("source", [
    "@decorate\ndef f(x): pass\n",
    "class f(Base):\n    def __init__(self, x): pass\n",
    "@decorate\nclass f:\n    def __init__(self, x): pass\n",
    "class f: pass\n",
])
def test_unknown_signatures_are_none(source):
    assert extract_symbols(source, "api", "api.py")["f"].params is None


@pytest.mark.parametrize("bases", ["", "(object)"])
def test_simple_class_signature_omits_receiver(bases):
    source = f"class Client{bases}:\n    def __init__(self, host, *, port=80): pass\n"
    symbol = extract_symbols(source, "api", "api.py")["Client"]
    assert symbol.params == (Param("host", "pos", False), Param("port", "kwonly", True))


def references(source, module="client", package=False):
    return extract_references(source, module, "client.py", package)


def test_from_import_alias_records_import_and_call_locations():
    refs = references("from billing import charge as pay\npay(1, currency='USD')\n")
    assert {(r.module, r.name, r.line, r.call) for r in refs} == {
        ("billing", "charge", 1, None),
        ("billing", "charge", 2, CallShape(1, ("currency",), False, False)),
    }
    assert all(r.path == "client.py" for r in refs)


def test_module_alias_and_attribute_references():
    refs = references("import pkg.billing as bill\nbill.charge(1)\nx = bill.charge\n")
    assert {(r.module, r.name, r.line, r.call) for r in refs} == {
        ("pkg.billing", "charge", 2, CallShape(1, (), False, False)),
        ("pkg.billing", "charge", 3, None),
    }


@pytest.mark.parametrize(("module", "package", "source", "target"), [
    ("pkg.client", False, "from .billing import charge", "pkg.billing"),
    ("pkg", True, "from .billing import charge", "pkg.billing"),
    ("pkg.sub.client", False, "from ..billing import charge", "pkg.billing"),
    ("pkg.sub", True, "from ..billing import charge", "pkg.billing"),
])
def test_relative_imports_use_package_context(module, package, source, target):
    refs = references(source, module, package)
    assert [(r.module, r.name) for r in refs] == [(target, "charge")]


@pytest.mark.parametrize("source", [
    "from ...billing import charge\ncharge(1)\n",
    "from billing import *\ncharge(1)\n",
    "import billing as b\nb.Client.method(1)\n",
    "import billing as b\ngetattr(b, 'charge')(1)\n",
    "import importlib\nimportlib.import_module('billing').charge(1)\n",
])
def test_unsupported_resolution_does_not_invent_charge_call(source):
    refs = references(source, "pkg.client")
    assert not [r for r in refs if r.name == "charge" and r.call is not None]


@pytest.mark.parametrize("shadow", [
    "pay = lambda x: x\n",
    "def f(pay):\n    pay(2)\n",
    "def pay(x): pass\n",
    "def f():\n    pay = lambda x: x\n",
])
def test_shadowing_anywhere_suppresses_imported_calls(shadow):
    refs = references("from billing import charge as pay\npay(1)\n" + shadow)
    assert not [r for r in refs if r.name == "charge" and r.call is not None]


def test_splatted_call_shape():
    refs = references("from api import f\nf(1, *args, named=2, **kwargs)\n")
    assert [r.call for r in refs if r.call is not None] == [CallShape(1, ("named",), True, True)]


def test_nested_import_is_supported():
    refs = references("def client():\n    from billing import charge\n    charge(1)\n")
    assert any(r.module == "billing" and r.name == "charge" and r.call for r in refs)


def test_public_model_is_frozen_and_slotted():
    param = Param("x", "pos", False)
    assert not hasattr(param, "__dict__")
    with pytest.raises(dataclasses.FrozenInstanceError):
        param.name = "other"


def test_invalid_python_raises_syntax_error_for_engine_to_handle():
    with pytest.raises(SyntaxError):
        extract_symbols("def broken(\n", "api", "api.py")
