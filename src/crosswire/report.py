import json
from dataclasses import asdict
from .coverage import text_lines


def text(report):
    """Text."""
    pairs = len(report.base_by_pair)
    if not report.findings:
        return '\n'.join([f'No semantic conflicts found across {pairs} pair(s).', *text_lines(report.coverage, report.limitations)])
    lines = [f'{f.path}:{f.line}: {f.severity.upper()} {f.rule} [{f.branch} × {f.other_branch}] {f.message}' + (f' Hint: {f.hint}' if f.hint else '')
             + ''.join(f' Limitation: {item}' for item in f.limitations) for f in report.findings]
    errors = sum(f.severity == 'error' for f in report.findings)
    lines.append(
        f'{errors} error(s), {len(report.findings)-errors} warning(s) across {pairs} pair(s)')
    lines.extend(text_lines(report.coverage, report.limitations))
    return '\n'.join(lines)


def json_report(report):
    """Json report."""
    errors = sum(f.severity == 'error' for f in report.findings)
    obj = {
        'version': 1, 'tool': 'crosswire', 'coverage': report.coverage, 'limitations': report.limitations or {}, 'pairs': [
            {
                'a': a, 'b': b, 'base': base} for (
                a, b), base in report.base_by_pair.items()], 'findings': [
                    asdict(f) for f in report.findings], 'summary': {
                        'errors': errors, 'warnings': len(
                            report.findings) - errors}}
    return json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=True)


def _escape(value, prop=False):
    value = str(value).replace(
        '%',
        '%25').replace(
        '\r',
        '%0D').replace(
            '\n',
        '%0A')
    return value.replace(':', '%3A').replace(',', '%2C') if prop else value


def github(report):
    """Render GitHub annotations."""
    lines = []
    for f in report.findings:
        message = f.message + (f' Hint: {f.hint}' if f.hint else '')
        message += ''.join(f' Limitation: {item}' for item in f.limitations)
        lines.append(f'::{f.severity} file={_escape(f.path, True)},line={f.line},title={_escape(f.rule, True)}::{_escape(message)}')
    lines.extend('::notice::' + _escape(line) for line in text_lines(report.coverage, report.limitations))
    return '\n'.join(lines)


def sarif(report):
    """Format deterministic SARIF 2.1.0 results for code scanning."""
    descriptions = {
        'CW001': 'Stale reference',
        'CW002': 'Incompatible call signature',
        'CW003': 'Duplicate definition',
        'CW004': 'Migration collision',
        'CW005': 'Textual conflict',
    }
    rules = [{'id': rule, 'shortDescription': {'text': description}}
             for rule, description in descriptions.items()]
    results = []
    for finding in report.findings:
        results.append({
            'ruleId': finding.rule,
            'level': finding.severity,
            'message': {'text': finding.message},
            'locations': [{'physicalLocation': {
                'artifactLocation': {'uri': finding.path},
                'region': {'startLine': finding.line},
            }}],
            'properties': {'branch': finding.branch,
                           'other_branch': finding.other_branch,
                           'symbol': finding.symbol, 'hint': finding.hint, 'limitations': list(finding.limitations)},
        })
    payload = {
        '$schema': 'https://json.schemastore.org/sarif-2.1.0.json',
        'version': '2.1.0',
        'runs': [{'tool': {'driver': {'name': 'crosswire', 'rules': rules}},
                  'results': results,
                  'properties': {'coverage': report.coverage, 'limitations': report.limitations or {}}}],
    }
    return json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True)


# Convenient explicit aliases for callers.
format_text = text
format_json = json_report
format_github = github

format_sarif = sarif
