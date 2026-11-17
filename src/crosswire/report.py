import json
from dataclasses import asdict


def text(report):
    """Text."""
    pairs = len(report.base_by_pair)
    if not report.findings:
        return f'No semantic conflicts found across {pairs} pair(s).'
    lines = [f'{f.path}:{f.line}: {f.severity.upper()} {f.rule} [{f.branch} × {f.other_branch}] {f.message}' for f in report.findings]
    errors = sum(f.severity == 'error' for f in report.findings)
    lines.append(
        f'{errors} error(s), {len(report.findings)-errors} warning(s) across {pairs} pair(s)')
    return '\n'.join(lines)


def json_report(report):
    """Json report."""
    errors = sum(f.severity == 'error' for f in report.findings)
    obj = {
        'version': 1, 'tool': 'crosswire', 'pairs': [
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
    """Github."""
    return '\n'.join(
        f'::{f.severity} file={_escape(f.path, True)},line={f.line},title={_escape(f.rule, True)}::{_escape(f.message)}' for f in report.findings)


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
                           'symbol': finding.symbol},
        })
    payload = {
        '$schema': 'https://json.schemastore.org/sarif-2.1.0.json',
        'version': '2.1.0',
        'runs': [{'tool': {'driver': {'name': 'crosswire', 'rules': rules}},
                  'results': results}],
    }
    return json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True)


# Convenient explicit aliases for callers.
format_text = text
format_json = json_report
format_github = github

format_sarif = sarif
