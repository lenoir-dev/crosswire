"""Render merge plans."""

import json


def json_report(report):
    """Render a deterministic JSON v2 merge plan."""
    return json.dumps(report, sort_keys=True, indent=2, ensure_ascii=True)


def text(report, target):
    """Render steps, explanations and blockers as text."""
    total = report['summary']['placed'] + report['summary']['blocked']
    lines = [f'Merge plan into {target} ({total} branch(es)):']
    for i, step in enumerate(report['steps'], 1):
        suffix = '   (merge together)' if step['together'] else ''
        lines.append(f"  {i}. {' + '.join(step['branches'])}{suffix} — {step['reason']}")
    if report['blocked']:
        lines.append('Blocked:')
        for entry in report['blocked']:
            if entry['findings']:
                finding = entry['findings'][0]
                line = f"  {entry['branch']}: {finding['path']}:{finding['line']} {finding['rule']} {finding['message']}"
                if entry.get('hint'):
                    line += f" — {entry['hint']}"
                lines.append(line)
            else:
                lines.append(f"  {entry['branch']}: {entry.get('hint', 'blocked by ordering constraints')}")
    if report['coverage'] == 'bounded':
        lines.append(f"Coverage: bounded ({', '.join(report['limits']['hit'])}) — unchecked combinations are not proven safe.")
    return '\n'.join(lines)
