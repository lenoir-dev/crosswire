"""PLAN §5: API deltas and occurrence-sensitive reference subtraction."""

from crosswire.diffing import added_references, api_changes
from crosswire.model import CallShape, Reference
from crosswire.python_analyzer import extract_symbols


def symbols(source):
    return extract_symbols(source, "billing", "billing.py")


def test_removed_symbol_with_unique_rename_hint():
    changes = api_changes(symbols("def charge(amount): pass\n"), symbols("def create_charge(amount): pass\n"))
    assert len(changes) == 1
    change = changes[0]
    assert (change.kind, change.module, change.qualname) == ("removed", "billing", "charge")
    assert change.old.qualname == "charge"
    assert change.new is None
    assert change.rename_hint == "create_charge"


def test_ambiguous_rename_has_no_hint():
    changes = api_changes(
        symbols("def charge(amount): pass\n"),
        symbols("def create_charge(amount): pass\ndef debit(amount): pass\n"),
    )
    assert changes[0].rename_hint is None


def test_existing_symbol_is_not_a_rename_candidate():
    changes = api_changes(
        symbols("def charge(amount): pass\ndef debit(amount): pass\n"),
        symbols("def debit(amount): pass\n"),
    )
    assert changes[0].rename_hint is None


def test_signature_changed_and_body_change_is_ignored():
    changes = api_changes(
        symbols("def charge(amount): return 1\ndef same(x): return 1\n"),
        symbols("def charge(amount, currency): return 1\ndef same(x): return 2\n"),
    )
    assert len(changes) == 1
    assert changes[0].kind == "signature_changed"
    assert changes[0].qualname == "charge"
    assert changes[0].new.params != changes[0].old.params


def test_unknown_signatures_do_not_generate_signature_changes():
    assert api_changes(symbols("@d\ndef f(x): pass\n"), symbols("@d\ndef f(x, y): pass\n")) == []
    assert api_changes(symbols("def f(x): pass\n"), symbols("@d\ndef f(x, y): pass\n")) == []


def test_new_symbol_is_not_an_api_break():
    assert api_changes({}, symbols("def charge(amount): pass\n")) == []


def ref(line, name="charge", call=None, path="client.py", module="billing"):
    return Reference(path, line, module, name, call)


def test_line_changes_do_not_add_references():
    assert added_references([ref(1), ref(2, call=CallShape(1, (), False, False))],
                            [ref(10), ref(20, call=CallShape(1, (), False, False))]) == []


def test_multiset_difference_keeps_last_surplus_occurrences():
    base = [ref(1), ref(2)]
    tip = [ref(40), ref(10), ref(30), ref(20)]
    assert sorted(r.line for r in added_references(base, tip)) == [30, 40]


def test_reference_identity_includes_path_target_and_call_shape():
    call = CallShape(1, (), False, False)
    new = [ref(2, call=call), ref(3, name="other"), ref(4, path="new.py"), ref(5, module="other")]
    assert sorted(added_references([ref(1)], new), key=lambda r: r.line) == new


def test_deleted_references_are_not_added():
    assert added_references([ref(1)], []) == []
