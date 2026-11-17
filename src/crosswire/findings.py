"""Shared deterministic consolidation of repeated use sites."""

from dataclasses import replace


def consolidate(findings):
    """Merge repeated findings for the same symbol and branch pair or culprit set."""
    groups = {}
    for finding in findings:
        other = getattr(finding, 'culprits', None)
        if other is None:
            other = getattr(finding, 'other_branch', None)
        key = (finding.rule, finding.branch, other, finding.path, finding.symbol)
        groups.setdefault(key, []).append(finding)
    result = []
    for group in groups.values():
        first = min(group, key=lambda item: (item.line, item.message))
        if len(group) > 1:
            first = replace(first, message=f'{first.message} ({len(group)} uses in this file)')
        result.append(first)
    return result
