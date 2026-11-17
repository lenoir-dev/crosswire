"""Independent harness validation: bad attribution cannot hide good detection."""

import pytest
import subprocess
import sys
from pathlib import Path
import json

from eval.metrics import aggregate, clustered, match, wilson
from eval.oracle import occurrence, reason_category


def diagnostic(**kwargs):
    return {"type": "PY-4", "path": "use.py", "symbol": "m.f", "occurrence": "call-1", "reason": "missing", **kwargs}


def test_m1_detection_and_attribution_are_separate():
    result = match([diagnostic(rule="CW002", attribution=False, reason="unknown keyword")], [diagnostic()])
    assert (result["tp"], result["fp"], result["fn"]) == (1, 0, 0)
    assert result["matches"][0]["attribution"] is False
    assert result["reason_mismatches"] == [{"prediction": "unknown keyword", "oracle": "missing"}]


def test_one_to_one_matching_counts_extra_predictions_as_false_positive():
    result = match([diagnostic(), diagnostic()], [diagnostic()])
    assert (result["tp"], result["fp"], result["fn"]) == (1, 1, 0)


@pytest.mark.parametrize("field", ["path", "symbol", "occurrence", "type"])
def test_matching_rejects_wrong_site_even_if_name_matches(field):
    result = match([diagnostic(**{field: "wrong"})], [diagnostic()])
    assert (result["tp"], result["fp"], result["fn"]) == (0, 1, 1)


def test_occurrence_fingerprint_ignores_line_shifts_but_not_call_expression():
    assert occurrence("import m\nm.f(1)\n", 2, "m.f") == occurrence("# header\nimport m\nm.f(1)\n", 3, "m.f")
    assert occurrence("import m\nm.f(1)\n", 2, "m.f") != occurrence("import m\nm.f(2)\n", 2, "m.f")
    assert occurrence("m.f(cast(Any, None))", 1, "m.f") != occurrence("m.g(cast(Any, None))", 1, "m.g")


def test_wilson_and_empty_metrics_do_not_claim_perfect_quality():
    assert wilson(0, 0) is None
    low, high = wilson(20, 20)
    assert .83 < low < .85 and high == pytest.approx(1)
    assert aggregate([])["precision"] is None
    assert aggregate([])["status"] == "insufficient data"


def test_unlabelled_rows_are_excluded_and_share_is_visible():
    result = aggregate([{"eligible": True, "tp": 1, "attribution": [None]}, {"eligible": False, "fp": 999}])
    assert result["precision"] == 1 and result["fp"] == 0
    assert result["unlabelled_share"] == .5 and result["attribution_accuracy"] is None


def test_repository_bootstrap_is_deterministic_and_resamples_clusters():
    rows = [{"repository": "a", "eligible": True, "tp": 20}, {"repository": "b", "eligible": True, "fp": 20, "fn": 20}]
    result = clustered(rows, replicates=100)
    assert result == clustered(rows, replicates=100)
    assert result["precision"] is None and result["status"] == "not estimable"
    rows.extend({"repository": str(i), "eligible": True, "tp": 20} for i in range(3))
    assert clustered(rows, replicates=100)["precision"] is not None
    assert clustered(rows[:1])["precision"] is None


def test_occurrence_fingerprint_is_identical_on_python_311_and_314():
    alternative = Path("/opt/homebrew/bin/python3.14")
    if not alternative.exists():
        pytest.skip("local alternate interpreter not installed")
    code = "from eval.oracle import occurrence; print(occurrence('import m\\nm.f(1)\\n', 2, 'm.f'))"
    first = subprocess.check_output([sys.executable, "-c", code], text=True)
    second = subprocess.check_output([str(alternative), "-c", code], text=True)
    assert first == second


def test_quality_gates_need_lower_bound_and_sample_size():
    assert aggregate([{"eligible": True, "tp": 10}])["precision_gate"] == "insufficient data"
    assert aggregate([{"eligible": True, "tp": 20}])["precision_gate"] == "fail"
    assert aggregate([{"eligible": True, "tp": 200}])["precision_gate"] == "pass"
    assert aggregate([{"eligible": True, "tp": 20, "fn": 10}])["recall_gate"] == "fail"


def test_public_mutator_preserves_body_type_ignores_and_updates_original_calls(tmp_path):
    import ast
    from eval.corpus import mutate, update_internal_uses

    package = tmp_path / "pkg"
    package.mkdir()
    source = 'def f(value: int) -> int:\n    return value  # type: ignore[return-value]\n\ndef existing():\n    return f(1)\n'
    node = ast.parse(source).body[0]
    candidate = {"source": source, "node": node, "path": "pkg/m.py", "name": "f", "line": 1, "end_line": 2}
    changed = mutate(candidate, "required_keyword")
    assert "# type: ignore[return-value]" in changed
    (package / "m.py").write_text(changed)
    update_internal_uses(tmp_path, {"roots": ["pkg"]}, candidate, "required_keyword")
    result = (package / "m.py").read_text()
    assert 'f(1, template="")' in result
    assert "# type: ignore[return-value]" in result
    ast.parse(result)


@pytest.mark.parametrize("override,expected", [
    ({}, "pass"),
    ({"version": "unapproved"}, "unlabelled"),
    ({"summary": {"filesAnalyzed": 0, "errorCount": 0}}, "unlabelled"),
    ({"summary": {"filesAnalyzed": 1, "errorCount": 1}}, "unlabelled"),
    ({"generalDiagnostics": None}, "unlabelled"),
])
def test_oracle_never_labels_incomplete_or_wrong_version_output_green(tmp_path, override, expected):
    from eval.oracle import run

    package = tmp_path / "pkg"
    package.mkdir()
    (package / "m.py").write_text("value = 1\n")
    data = {"version": "1.1.407", "summary": {"filesAnalyzed": 1, "errorCount": 0}, "generalDiagnostics": [], **override}
    checker = tmp_path / "checker"
    checker.write_text(f"#!{sys.executable}\nprint({json.dumps(json.dumps(data))})\n")
    checker.chmod(0o755)
    assert run(tmp_path, ["pkg"], sys.executable, str(checker)).status == expected


def test_holdout_export_guard_rejects_case_level_fields_without_reading_private_data():
    from eval.run_holdout import assert_aggregate_only

    assert_aggregate_only({"micro": {"tp": 6, "fp": 0}, "by_rule": {"CW001": {"precision": 1.0}}})
    for payload in ({"rows": []}, {"micro": {"symbol": "private"}}, {"reason": ".crosswire-holdout/case"}):
        with pytest.raises(AssertionError):
            assert_aggregate_only(payload)
