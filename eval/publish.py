"""Publish the R2 development pilot; holdout measurement is forbidden in v0.4."""
import argparse
import json
from pathlib import Path


def percent(value):return f'{value:.1%}' if value is not None else 'not estimable'
def interval(value):return 'not estimable' if value is None else f'{value[0]:.1%}–{value[1]:.1%}'


def table(summary):
    lines=['| Rule | TP / FP / FN | Precision (Wilson 95%) | Recall (Wilson 95%) | Attribution | Status |','| --- | --- | --- | --- | --- | --- |']
    for rule,v in summary['by_rule'].items():
        lines.append(f"| {rule} | {v['tp']} / {v['fp']} / {v['fn']} | {percent(v['precision'])} ({interval(v['precision_wilson95'])}) | {percent(v['recall'])} ({interval(v['recall_wilson95'])}) | {percent(v['attribution_accuracy'])} | {v['status']} |")
    return lines


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--development',type=Path,default=Path('docs/validation/v04-development-results.json'));p.add_argument('--output',type=Path,default=Path('docs/validation/v0.4.md'));args=p.parse_args()
    data=json.loads(args.development.read_text());summary=data['metrics'];m=summary['micro']
    lines=['# v0.4 Python pilot','', '**Development data, optimistic, not a gate.** No holdout has been measured in v0.4.','',
    'PLAN v0.4 R2 supersedes the earlier pilot protocol. The old exposed holdout is retired and never measured. A new private v2 corpus is sealed for a separately authorized v0.5 checkpoint. Only its hash list is public. All workers use one OS account: isolation is procedural (instructions and independent audit), not an OS security boundary.','',
    '## Development evidence','',
    'Historical production-declaration mutations have been re-screened with repository tests included. Supplemental hard negatives and three-branch cases use explicit probe wrappers around real upstream API objects; these are an **upstream API oracle-scaffold** stratum, not natural upstream merge incidents or direct edits of upstream declarations. Whole-repository diversity and representative failures remain limited.', '',
    'The identical pinned Pyright basic configuration covers production roots, every discovered test directory and the new consumers at target, all tips, integrated state and attribution subsets. Focused runtime smoke checks validate ambiguous export controls. Non-green parents and oracle/environment failures remain unlabelled. Detector crashes/timeouts remain FN on oracle positives and are counted separately.','', *table(summary),'',
    f"Micro precision {percent(m['precision'])}; recall {percent(m['recall'])}; attribution {percent(m['attribution_accuracy'])} over {m['attribution_labelled']} labelled detection TPs. Detector failures: {m['detector_errors']}.",
    f"Outside-scope/unlabelled predictions: {m['unlabelled_predictions']} ({percent(m['unlabelled_prediction_share'])}); ineligible cases: {m['unlabelled_cases']} ({percent(m['unlabelled_share'])}). All exclusions and individual outcomes are retained in the public raw development evidence.",
    f"Repository-clustered 95% intervals: precision {interval(summary['repo_clustered95']['precision'])}, recall {interval(summary['repo_clustered95']['recall'])}. Below five eligible repositories the clustered interval is not estimable. For future valid gates the lower bound is the stricter of Wilson and clustered bounds; all current results remain development-only.", '',
    'CW003 warnings and CW005 textual conflicts are excluded from semantic precision/recall. CW004/PY-6 has no migration oracle here. Empty cells and cells below 20 predictions or positives remain insufficient data. Exact labels, patches, SHAs, source hashes and oracle subset results are in the development manifest and measurement rows.','',
    '## Every development miss and false positive','', '| Case | FP | FN | Root-cause evidence |','| --- | ---: | ---: | --- |']
    for row in data['rows']:
        if not (row.get('fp') or row.get('fn')):continue
        expected='; '.join(f"{d.get('type')} {d.get('path')} {d.get('symbol')}" for d in row.get('misses',[]))
        emitted='; '.join(f"{d.get('rule')} {d.get('type')} {d.get('path')} {d.get('symbol')}" for d in row.get('false_positives',[]))
        reason='detector failure: '+row['detector_failure'] if row.get('detector_failure') else 'unmatched oracle use site: '+expected+'; unmatched emitted prediction: '+emitted
        lines.append(f"| {row['id']} | {row.get('fp',0)} | {row.get('fn',0)} | {reason} |")
    lines+=['','CW002 reason disagreement is diagnostic quality only; matching accepts any oracle category at the same root cause.','']
    for row in data['rows']:
        for mismatch in row.get('reason_mismatches',[]):lines.append(f"- `{row['id']}`: detector `{mismatch['prediction']}`, oracle `{mismatch['oracle']}`.")
    lines+=['','## PR snapshot noise','']
    live_path=Path('docs/validation/v04-live-prs.json')
    if live_path.exists():
        live=json.loads(live_path.read_text());lines += [f"Stratum: **{live['stratum']}**. This estimates candidate noise per 100 PR pairs, not labelled semantic precision. Parent/merge oracle eligibility is not established; zero findings cannot pass a precision gate.",'','| Repository | Heads | Pairs | Semantic predictions | Flags / 100 pairs |','| --- | ---: | ---: | ---: | ---: |']
        for row in live['repositories']:lines.append(f"| {row['repository']} | {len(row['prs'])} | {row['pairs']} | {row['semantic_predictions']} | {row['potential_noise_per_100_pairs']:.2f} |")
    lines+=['','## Reliability and performance','']
    for file in ['v04-checks.json','v04-vega-perf.json','v04-perf-matrix.json']:
        path=Path('docs/validation')/file
        if not path.exists():lines.append(f'Pending: `{file}`.');continue
        evidence=json.loads(path.read_text())
        if 'checks' in evidence:
            for c in evidence['checks']:lines.append(f"- `{c['command']}`: {c['result']}")
        else:
            lines += [f"`{file}`: {evidence.get('processor')}, {evidence.get('memory_bytes')} bytes RAM; {evidence['platform']}; Python {evidence['python'].splitlines()[0]}; {evidence['git']}. RSS units: {evidence['rss_units']}; {evidence['rss_scope']}. Timeout {evidence['timeout_seconds']} s; censored samples retain lower bounds and do not produce successful-subset quantiles.",'','| Files | Branches | Mode | Cache | p50 s | p95 s | Censored |','| ---: | ---: | --- | --- | ---: | ---: | ---: |']
            for c in evidence['cells']:lines.append(f"| {c['files']} | {c['branches']} | {c['mode']} | {c['cache']} | {c.get('p50')} | {c.get('p95')} | {c.get('censored',sum(r['status']=='timeout' for r in c['samples']))} |")
            if 'budget_seconds' in evidence:lines.append(f"Vega scenario warm budget: ≤ {evidence['budget_seconds']} s; {evidence['cells'][0].get('budget')}.")
    lines += ['','Performance budgets are platform-specific baseline proposals, subject to Polaris acceptance; the Vega 9k-file/16-branch warm plan budget is already fixed at ≤15 s. No v1.0 quality gate is claimed.']
    args.output.write_text('\n'.join(lines)+'\n')


if __name__=='__main__':main()
