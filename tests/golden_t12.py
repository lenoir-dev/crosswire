"""Independent, data-only golden transformation allowed by PLAN-v0.3b T12."""

import copy
import json


def coalesce_report(report):
    result = copy.deepcopy(report)
    groups = {}
    for finding in result["findings"]:
        key = (finding["rule"], finding["branch"], finding["other_branch"], finding["path"], finding["symbol"])
        groups.setdefault(key, []).append(finding)
    findings = []
    for group in groups.values():
        first = min(group, key=lambda f: f["line"])
        if len(group) > 1:
            first["message"] += f" ({len(group)} uses in this file)"
        findings.append(first)
    findings.sort(key=lambda f: (f["path"], f["line"], f["rule"], f["branch"], f["other_branch"], f["symbol"] or "", f["message"]))
    result["findings"] = findings
    if "summary" in result:
        result["summary"] = {"errors": sum(f["severity"] == "error" for f in findings),
                             "warnings": sum(f["severity"] == "warning" for f in findings)}
    return result


def coalesce_case(key, value):
    if "::analyze::" in key:
        return coalesce_report(value)
    result = copy.deepcopy(value)
    stdout = result["stdout"]
    # All merging CLI scenarios in the archived corpus are JSON; non-JSON stays exact.
    if stdout.lstrip().startswith("{"):
        report = coalesce_report(json.loads(stdout))
        result["stdout"] = json.dumps(report, sort_keys=True, indent=2) + ("\n" if stdout.endswith("\n") else "")
    return result
