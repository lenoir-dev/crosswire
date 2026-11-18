"""Census bookkeeping and independent category extraction, no private evidence."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("s19a_census", Path(__file__).parents[1] / "benchmarks/s19a_census.py")
census = importlib.util.module_from_spec(spec)
spec.loader.exec_module(census)


@pytest.mark.parametrize("code,syntax,rule", [
    ("UndeclaredImportedName", "package-selector", "GO-1"),
    ("WrongArgCount", "bare-call", "GO-3"),
    ("DuplicateDecl", "other", "GO-4"),
    ("DuplicateDecl", "import", "GO-7"),
    ("WrongAssignCount", "multi-assignment-call", "GO-6"),
    ("WrongAssignCount", "assignment", None),
    ("UnusedImport", "import", "GO-7"),
    ("UndeclaredName", "bare-call", "GO-9"),
    ("UndeclaredName", "other", None),
    ("BrokenImport", "import", None),
])
def test_category_depends_on_code_and_syntax_never_prose(code, syntax, rule):
    assert census.category({"category":code,"syntax":syntax,"message":"arbitrary unrelated prose"}) == rule


def test_cycle_detection_uses_graph_and_ignores_external_nodes():
    packages = [{"ImportPath":"a","Imports":["b","stdlib"]}, {"ImportPath":"b","Imports":["a"]},
                {"ImportPath":"c","Imports":["stdlib"]}]
    assert census.import_cycles(packages) == [["a","b"]]


def test_position_parser_and_json_stream_preserve_identity():
    assert census.compiler_positions("# pkg\n./a.go:4:12: prose\n\tcontinued\n") == [{"path":"a.go","line":4,"column":12}]
    assert census.json_stream('{"a":1}\n {"b":2}') == [{"a":1},{"b":2}]


def test_offline_environment_and_portable_evidence(tmp_path):
    env = census.environment(tmp_path)
    assert env["GOPROXY"] == env["GOSUMDB"] == "off"
    assert env["GOTOOLCHAIN"] == "local" and env["GOFLAGS"] == "-mod=readonly"
    value = {"path":str(tmp_path / "states/repo/m.go")}
    assert census.portable(value,tmp_path,Path('/toolchain')) == {"path":"${CENSUS}/states/repo/m.go"}


def test_compiler_and_checker_offsets_must_name_same_syntax_span():
    diagnostic={"path":"m.go","line":3,"column":4,"start_line":3,"start_column":2,"end_line":3,"end_column":5}
    assert census.same_site(diagnostic,{"path":"m.go","line":3,"column":2})
    assert not census.same_site(diagnostic,{"path":"m.go","line":3,"column":8})
    assert not census.same_site(diagnostic,{"path":"other.go","line":3,"column":2})
