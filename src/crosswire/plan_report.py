"""Render merge plans."""

import json
from .coverage import text_lines


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
                for finding in entry['findings']:
                    line = f"  {entry['branch']}: {finding['path']}:{finding['line']} {finding['rule']} {finding['message']}"
                    advice = finding.get('hint') or entry.get('hint')
                    if finding['rule'] == 'CW005' and entry.get('hint'):
                        advice = entry['hint']
                    if advice:
                        line += f" — {advice}"
                    if finding.get('repro'):
                        line += f" Reproduce: {finding['repro']}"
                    for limitation in finding.get('limitations', ()):
                        line += f" Limitation: {limitation}"
                    lines.append(line)
            else:
                lines.append(f"  {entry['branch']}: {entry.get('hint', 'blocked by ordering constraints')}")
    lines.extend(text_lines(report['coverage'], report.get('limitations'), report.get('limits')))
    return '\n'.join(lines)
