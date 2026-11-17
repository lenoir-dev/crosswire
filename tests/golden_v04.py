"""Prove v0.4 additive metadata preserves historical finding meaning and locations."""

import copy
import json


def project_finding(finding):
    return {key: value for key, value in finding.items() if key not in {"hint", "limitations", "repro"}}


def project_report(report):
    result = copy.deepcopy(report)
    result.pop("limitations", None)
    # v1 gains coverage; v2 had coverage and limits already.
    if result.get("version") == 1:
        result.pop("coverage", None)
        result.pop("limits", None)
    result["findings"] = [project_finding(finding) for finding in result["findings"]]
    return result


def project_case(key, payload):
    result = copy.deepcopy(payload)
    if "::analyze::" in key:
        result["findings"] = [project_finding(finding) for finding in result["findings"]]
        return result
    stdout = result["stdout"]
    if stdout.lstrip().startswith("{"):
        data = json.loads(stdout)
        result["stdout"] = json.dumps(project_report(data), sort_keys=True, indent=2) + ("\n" if stdout.endswith("\n") else "")
    else:
        # T14 adds advice after the original text/annotation message, preserving its prefix.
        result["stdout"] = "".join(
            line.split(" Hint: ", 1)[0].rstrip("\n") + ("\n" if line.endswith("\n") else "")
            if " Hint: " in line and (" CW00" in line or line.startswith(("::error ", "::warning ")))
            else line for line in stdout.splitlines(keepends=True)
            if not line.startswith(("Coverage:", "Limitation:")))
    return result
