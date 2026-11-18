"""Publish combined development summaries without running either measured tool."""
import argparse
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

from benchmarks.s17 import run
from benchmarks.s17.m3 import Identity
from benchmarks.s17.matching import match
from benchmarks.s17.metrics import aggregate, clustered


def report(root, cohorts, output):
    run.verify_freeze()
    cases = []
    inputs = {}
    repositories = {}
    case_refs = []
    for cohort in cohorts:
        result = json.loads((cohort/'results.json').read_text())
        selection = json.loads((cohort/'selection.json').read_text())
        assert result['selection_sha256'] == run.sha(cohort/'selection.json')
        assert all(result[k] for k in ('source_stable', 'oracle_stable', 'apparatus_stable'))
        expected = {(s['id'], c['merge']) for s in selection['repositories'] for c in s['cases']}
        assert expected == {(c['repository'], c['merge']) for c in result['cases']}
        for filename in ('selection.json', 'results.json'):
            inputs[(cohort/filename).relative_to(run.ROOT).as_posix()] = run.sha(cohort/filename)
        repositories.update({s['id']: {k:s[k] for k in ('url', 'head', 'domain')} for s in selection['repositories']})
        for case in result['cases']:
            path = cohort/'cases'/case['repository']/(case['merge']+'.json')
            assert json.loads(path.read_text()) == case
            cases.append(case)
            case_refs.append({'path':path.relative_to(run.ROOT).as_posix(), 'sha256':run.sha(path)})
    assert len({(c['repository'], c['merge']) for c in cases}) == len(cases)
    typed = {f'PY-{n}':[] for n in range(1,6)}
    for case in cases:
        values = {key:dict(tp=0, fp=0, fn=0) for key in typed}
        if case['eligible']:
            repo = root/'repositories'/case['repository']
            base = run.files_at(repo,case['target'])[0]
            integrated = run.files_at(repo,case['native_commit'])[0]
            base = {p:s for p,s in base.items() if p in case['scope']}
            integrated = {p:s for p,s in integrated.items() if p in case['scope']}
            diagnostics = tuple(Identity(**d) for d in case['new_supported_diagnostics'])
            findings = case.get('detector',{}).get('report',{}).get('findings',[])
            matched = match(findings, diagnostics, base, integrated, case['known_modules'])
            assert all(matched[k] == case['metrics'][k] for k in ('tp','fp','fn'))
            for name, field in [('matches','tp'),('false_positives','fp'),('misses','fn')]:
                for item in matched[name]:
                    values[item['type']][field] += 1
        for key in typed:
            typed[key].append(dict(repository=case['repository'],eligible=case['eligible'],**values[key]))
    rows = run.metric_rows(cases)
    result = dict(
        stratum='natural-development-M3', apparatus_freeze_sha256=run.sha(run.FREEZE),
        report_driver_sha256=run.sha(__file__), inputs_sha256=inputs, cases=case_refs,
        summary=aggregate(rows), repo_clustered95=clustered(rows),
        by_rule={rule:dict(**aggregate(run.metric_rows(cases,rule)),repo_clustered95=clustered(run.metric_rows(cases,rule))) for rule in run.RULES},
        by_type={key:dict(**aggregate(values),repo_clustered95=clustered(values)) for key,values in typed.items()},
        labels=dict(Counter(c['label'] for c in cases)),
        exclusions=dict(Counter(c.get('exclusion') for c in cases if not c['eligible'])),
        repositories={name:dict(**spec,attempted=sum(c['repository']==name for c in cases),
            eligible=sum(c['repository']==name and c['eligible'] for c in cases)) for name,spec in repositories.items()},
        warning_counts={rule:sum(c.get('warning_counts',{}).get(rule,0) for c in cases) for rule in ('CW003','CW004','CW005')},
        detector_errors=[dict(repository=c['repository'],merge=c['merge'],reason=c['detector_error']) for c in cases if c.get('detector_error')],
        false_positives=[dict(repository=c['repository'],merge=c['merge'],**f) for c in cases for f in c.get('false_positives',[])],
        misses=[dict(repository=c['repository'],merge=c['merge'],**m) for c in cases for m in c.get('misses',[])],
        attribution=[dict(repository=c['repository'],merge=c['merge'],**a) for c in cases for a in c.get('attribution',[])],
        detector_execution_scope='oracle-eligible cases only; prediction share over excluded cases is not estimable',
        audit_status='Independent label sample and all-FP audit pending Vega; no release acceptance claim',
        controller_provenance=dict(python=sys.version, executable_sha256=hashlib.sha256(Path(sys.executable).resolve().read_bytes()).hexdigest(),
            ast_module_sha256=hashlib.sha256(Path(ast.__file__).read_bytes()).hexdigest(),
            recorded='post-run observation, not an additional pre-label freeze pin'),
        machine=dict(system=platform.system(),release=platform.release(),machine=platform.machine(),
            macos=platform.mac_ver()[0],git=subprocess.check_output(['git','--version']).decode().strip()),
        source_stable=True,oracle_stable=True,apparatus_stable=True,
    )
    run.write(output,result,root)
    print(json.dumps({key:result[key] for key in ('summary','labels','exclusions','warning_counts')}))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True,type=Path)
    parser.add_argument('--cohort',required=True,action='append',type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    report(args.root.resolve(),[p.resolve() for p in args.cohort],args.output.resolve())


if __name__=='__main__':main()
