"""Synthetic checker identities, declared before M3 implementation/labels."""
import pytest

from benchmarks.s17.identity import identify_files
from benchmarks.s17.m3 import delta


def error(path,line,column=0,rule="reportCallIssue",length=1):
    return {"file":path,"rule":rule,"message":"arbitrary checker prose","severity":"error",
            "range":{"start":{"line":line-1,"character":column},"end":{"line":line-1,"character":column+length}}}


API="def f(value: int) -> int:\n    return value\n"


def identify(files,errors,**kwargs):
    return identify_files(files,errors,known_modules={"api":"api.py","use":"use.py"},files_analyzed=len(files),**kwargs)


def test_line_shifts_preserve_five_component_identity_without_message_parsing():
    old={"api.py":API,"use.py":"import api\napi.f()\n"}
    new={"api.py":API,"use.py":"# shifted\nimport api\napi.f()\n"}
    a=identify(old,[error("use.py",2)])
    b=identify(new,[error("use.py",3)])
    assert a.diagnostics==b.diagnostics and delta(a,b).new==()
    assert a.diagnostics[0].symbol=="api.f"


def test_repeated_identical_call_sites_are_ambiguous_not_ordinally_guessed():
    files={"api.py":API,"use.py":"import api\napi.f()\napi.f()\n"}
    result=identify(files,[error("use.py",2),error("use.py",3)])
    assert result.ambiguous


def test_same_count_new_call_is_not_subtracted_from_an_old_error():
    old=identify({"api.py":API,"use.py":"import api\napi.f()\n"},[error("use.py",2)])
    new=identify({"api.py":API,"use.py":"import api\napi.f(1, 2)\n"},[error("use.py",2)])
    assert len(delta(old,new).new)==1


def test_missing_external_dependency_is_environment_not_a_control():
    result=identify({"use.py":"import absent_external\n"},[error("use.py",1,rule="reportMissingImports")])
    assert result.environment_failure


def test_missing_first_party_module_keeps_a_module_identity():
    result=identify({"use.py":"import api\n"},[error("use.py",1,rule="reportMissingImports")])
    assert not result.environment_failure and result.diagnostics[0].symbol=="api"


def test_incomplete_scope_and_unparseable_sources_are_not_complete():
    files={"api.py":API,"use.py":"import api\n"}
    assert not identify_files(files,[],known_modules={},files_analyzed=1).complete
    assert not identify({"use.py":"def broken(\n"},[]).complete


def test_same_expression_in_different_scopes_does_not_collapse():
    files={"api.py":API,"use.py":"import api\ndef left():\n    api.f()\ndef right():\n    api.f()\n"}
    result=identify(files,[error("use.py",3,4),error("use.py",5,4)])
    assert not result.ambiguous and len(set(result.diagnostics))==2


def test_dynamic_or_method_call_is_not_promoted_to_supported_call_type():
    result=identify({"api.py":API,"use.py":"def test(obj):\n    obj.method()\n"},[error("use.py",2,4)])
    assert result.supported==()


def test_same_call_against_a_changed_definition_has_a_different_root_cause():
    old=identify({"api.py":"def f(a: int, b: int) -> int:\n    return a\n","use.py":"import api\napi.f(1)\n"},[error("use.py",2)])
    new=identify({"api.py":"def f(a: int, *, c: int) -> int:\n    return a\n","use.py":"import api\napi.f(1)\n"},[error("use.py",2)])
    assert old.diagnostics[0].occurrence==new.diagnostics[0].occurrence
    assert old.diagnostics[0].root_cause!=new.diagnostics[0].root_cause
    assert len(delta(old,new).new)==1


def test_import_alias_shadowed_by_a_parameter_is_not_a_proven_module_call():
    result=identify({"api.py":API,"use.py":"import api\ndef test(api):\n    api.f()\n"},[error("use.py",3,4)])
    assert result.ambiguous and result.supported==()


def test_module_level_alias_reassignment_is_also_ambiguous():
    result=identify({"api.py":API,"use.py":"import api\napi = object()\napi.f()\n"},[error("use.py",3)])
    assert result.ambiguous and result.supported==()
