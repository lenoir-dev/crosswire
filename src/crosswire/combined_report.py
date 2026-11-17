"""Format combined-mode reports without changing pairwise output contracts."""

import json
from dataclasses import asdict

from .report import _escape
from .coverage import text_lines


def json_report(report):
    """Return the version 2 combined report as JSON."""
    errors = sum(f.severity == 'error' for f in report.findings)
    payload = {
        'version': 2, 'tool': 'crosswire', 'mode': 'combined', 'target': report.target,
        'coverage': report.coverage, 'limits': report.limits, 'limitations': report.limitations or {},
        'integrated': report.integrated,
        'skipped': [{'branch': label, 'paths': paths} for label, paths in report.skipped],
        'findings': [asdict(f) for f in report.findings],
        'summary': {'errors': errors, 'warnings': len(report.findings) - errors},
    }
    return json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True)


def text(report):
    """Render combined findings for a terminal."""
    if not report.findings:
        line = f'No semantic conflicts found across {len(report.integrated)} integrated branch(es).'
        return '\n'.join([line, *text_lines(report.coverage, report.limitations, report.limits)])
    lines = []
    for f in report.findings:
        line = f'{f.path}:{f.line}: {f.severity.upper()} {f.rule} [{f.branch} × {{{", ".join(f.culprits)}}}] {f.message}'
        if f.resolved_by is not None:
            line += f' (resolved by {{{", ".join(f.resolved_by)}}})'
        if f.hint:
            line += f' Hint: {f.hint}'
        if f.repro:
            line += f' Reproduce: {f.repro}'
        line += ''.join(f' Limitation: {item}' for item in f.limitations)
        lines.append(line)
    errors = sum(f.severity == 'error' for f in report.findings)
    lines.append(f'{errors} error(s), {len(report.findings) - errors} warning(s) across {len(report.integrated)} integrated branch(es)')
    lines.extend(text_lines(report.coverage, report.limitations, report.limits))
    return '\n'.join(lines)


def github(report):
    """Render combined findings as GitHub workflow annotations."""
    lines = []
    for f in report.findings:
        details = f'{f.message} (culprits: {", ".join(f.culprits)})'
        if f.hint:
            details += f' Hint: {f.hint}'
        if f.repro:
            details += f' Reproduce: {f.repro}'
        if f.resolved_by is not None:
            details += f' (resolved by: {", ".join(f.resolved_by)})'
        details += ''.join(f' Limitation: {item}' for item in f.limitations)
        lines.append(f'::{f.severity} file={_escape(f.path, True)},line={f.line},title={_escape(f.rule, True)}::{_escape(details)}')
    lines.extend('::notice::' + _escape(line) for line in text_lines(report.coverage, report.limitations, report.limits))
    return '\n'.join(lines)


def sarif(report):
    """Render combined findings as SARIF 2.1.0."""
    descriptions = {'CW001': 'Stale reference', 'CW002': 'Incompatible call signature',
                    'CW003': 'Duplicate definition', 'CW004': 'Migration collision',
                    'CW005': 'Textual conflict', 'CW006': 'Combined break'}
    rules = [{'id': rule, 'shortDescription': {'text': desc}} for rule, desc in descriptions.items()]
    results = []
    for f in report.findings:
        results.append({'ruleId': f.rule, 'level': f.severity, 'message': {'text': f.message},
                        'locations': [{'physicalLocation': {'artifactLocation': {'uri': f.path},
                                                            'region': {'startLine': f.line}}}],
                        'properties': {'branch': f.branch, 'culprits': list(f.culprits),
                                       'culprits_exact': f.culprits_exact,
                                       'resolved_by': list(f.resolved_by) if f.resolved_by is not None else None,
                                       'symbol': f.symbol, 'location': f.location, 'hint': f.hint,
                                       'limitations': list(f.limitations), 'repro': f.repro}})
    return json.dumps({'$schema': 'https://json.schemastore.org/sarif-2.1.0.json', 'version': '2.1.0',
                       'runs': [{'tool': {'driver': {'name': 'crosswire', 'rules': rules}},
                                 'results': results, 'properties': {'coverage': report.coverage,
                                 'limitations': report.limitations or {}, 'limits': report.limits}}]}, sort_keys=True, indent=2, ensure_ascii=True)
