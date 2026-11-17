"""A2 permits only canonical orientation changes inside CW005 golden findings."""

import copy
import hashlib
import json
from pathlib import Path
import re


GOLDEN = Path(__file__).parent / "golden"
ORIGINAL_SHA256 = "b49a78c31843cf88185a067371a6045d2198d928719ae86b569d099fd00bb834"


def canonical_report(report):
    result = copy.deepcopy(report)
    for finding in result["findings"]:
        if finding["rule"] == "CW005":
            first, last = sorted((finding["branch"], finding["other_branch"]))
            finding.update(branch=last, other_branch=first, message=f"textual conflict with {first}")
    result["findings"].sort(key=lambda f: (
        f["path"], f["line"], f["rule"], f["branch"], f["other_branch"], f["symbol"] or "", f["message"],
    ))
    return result


def escape_message(value):
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def canonical_case(key, value, cases):
    result = copy.deepcopy(value)
    if "::analyze::" in key:
        return canonical_report(result)
    stdout = result["stdout"]
    if stdout.lstrip().startswith("{"):
        result["stdout"] = json.dumps(canonical_report(json.loads(stdout)), sort_keys=True, indent=2) + ("\n" if stdout.endswith("\n") else "")
    elif " ERROR CW005 " in stdout:
        lines = []
        for line in stdout.splitlines(keepends=True):
            if " ERROR CW005 " in line:
                def replace(match):
                    first, last = sorted((match[1], match[2]))
                    return f"[{last} × {first}] textual conflict with {first}"
                line = re.sub(r"\[([^ ]+) × ([^\]]+)\] textual conflict with [^\r\n]*", replace, line)
            lines.append(line)
        result["stdout"] = "".join(lines)
    elif ",title=CW005::" in stdout:
        # GitHub annotations omit branch labels; recover them from that test's JSON output.
        prefix = key.split("::cli::")[0] + "::"
        for sibling, payload in cases.items():
            if sibling.startswith(prefix) and "::cli::" in sibling and payload["stdout"].lstrip().startswith("{"):
                for finding in json.loads(payload["stdout"])["findings"]:
                    if finding["rule"] == "CW005":
                        other = min(finding["branch"], finding["other_branch"])
                        stdout = stdout.replace(
                            ",title=CW005::" + escape_message(finding["message"]),
                            ",title=CW005::" + escape_message(f"textual conflict with {other}"),
                        )
        result["stdout"] = stdout
    return result


def test_a2_preserves_all_non_cw005_v01_outputs_exactly():
    original_bytes = (GOLDEN / "v01-original.json").read_bytes()
    assert hashlib.sha256(original_bytes).hexdigest() == ORIGINAL_SHA256, "Original v0.1 recording was modified"
    original = json.loads(original_bytes)["cases"]
    updated = json.loads((GOLDEN / "v01.json").read_text())["cases"]
    assert updated.keys() == original.keys()
    for key, value in original.items():
        if "CW005" not in json.dumps(value):
            assert updated[key] == value, f"A2 changed a non-CW005 v0.1 output: {key}"
        else:
            assert updated[key] == canonical_case(key, value, original), f"A2 changed more than CW005 orientation: {key}"
