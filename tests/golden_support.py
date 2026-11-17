"""Record/verify v0.1 public outputs; opt-in recording uses an isolated source tree."""

from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path


GOLDEN_PATH = Path(__file__).parent / "golden" / "v01.json"
COUNTS = {}
RECORDED = {}
BASELINE = None


def case_name():
    return os.environ.get("PYTEST_CURRENT_TEST", "").rsplit(" (", 1)[0]


def baseline():
    global BASELINE
    if BASELINE is None:
        BASELINE = json.loads(GOLDEN_PATH.read_text()) if GOLDEN_PATH.exists() else {"cases": {}}
    return BASELINE


def enabled_for_case():
    return os.environ.get("CROSSWIRE_GOLDEN_RECORD") == "1" or any(
        key.startswith(case_name() + "::") for key in baseline()["cases"]
    )


def capture(kind, payload):
    if not enabled_for_case():
        return
    counter = (case_name(), kind)
    index = COUNTS.get(counter, 0)
    COUNTS[counter] = index + 1
    key = f"{case_name()}::{kind}::{index}"
    if os.environ.get("CROSSWIRE_GOLDEN_RECORD") == "1":
        RECORDED[key] = payload
    else:
        assert key in baseline()["cases"], f"Unexpected extra public output: {key}"
        assert payload == baseline()["cases"][key], f"v0.1 golden mismatch: {key} (PLAN-v0.2 §12.1/§12.5)"


def capture_report(report):
    capture("analyze", {
        "base_by_pair": [{"a": pair[0], "b": pair[1], "base": sha} for pair, sha in report.base_by_pair.items()],
        "findings": [asdict(finding) for finding in report.findings],
    })


def finish_recording():
    if os.environ.get("CROSSWIRE_GOLDEN_RECORD") == "1":
        output = Path(os.environ.get("CROSSWIRE_GOLDEN_OUTPUT", str(GOLDEN_PATH)))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({
            "provenance": {
                "commit": "562deeb",
                "full_commit": "562deeb51105bdf2b5d89a202878ec50e9d3f6d2",
                "source": "isolated git worktree at commit 562deeb",
                "command": "CROSSWIRE_GOLDEN_RECORD=1 CROSSWIRE_GOLDEN_SOURCE=/tmp/crosswire-sol-v01-562deeb/src PYTHONPATH=/tmp/crosswire-sol-v01-562deeb/src uv run pytest -q tests/test_git.py tests/test_python_analyzer.py tests/test_diffing.py tests/test_rules.py tests/test_cli.py tests/test_amendment_a1.py",
            },
            "cases": RECORDED,
        }, indent=2, sort_keys=True) + "\n")
