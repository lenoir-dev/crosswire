"""Publication from frozen mutation journals; never runs either measured tool."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import tarfile
from datetime import datetime,timezone

from .run import ROOT,SELECTION,FREEZE,MODES,RULES,verify,sha,write
from benchmarks.s17.metrics import aggregate,clustered

TYPES=tuple(f'PY-{n}' for n in range(1,6))


def rule_for(type_):return 'CW002' if type_=='PY-4' else 'CW006' if type_=='PY-5' else 'CW001'


def summarize(evidence,root):
    verify();selection=json.loads(SELECTION.read_text());cases=[]
    for item in selection['cases']:
        path=evidence/'cases'/(item['id']+'.json')
        if not path.exists():raise ValueError('Incomplete journal: '+item['id'])
        case=json.loads(path.read_text())
        assert case['freeze_sha256']==sha(FREEZE)
        cases.append(case)
    results={}
    for mode in MODES:
        rows=[];cells={(r,t):[] for r in RULES for t in TYPES}
        errors=[];attribution=[]
        for case in cases:
            value=case['modes'][mode]
            row={'repository':case['repository'],**{k:value.get(k,0) for k in ('tp','fp','fn','unlabelled_predictions','detector_error')},'eligible':value['eligible']}
            row['detector_error']=bool(value.get('detector_error'))
            rows.append(row)
            counts={(r,t):{'tp':0,'fp':0,'fn':0} for r,t in cells}
            for hit in value.get('matches',[]):counts[(hit['finding']['rule'],hit['type'])]['tp']+=1
            for fp in value.get('false_positives',[]):
                counts[(fp['finding']['rule'],fp['type'])]['fp']+=1
                finding=fp['finding']
                errors.append({'case':case['id'],'repository':case['repository'],'kind':'FP','rule':finding['rule'],'type':fp['type'],
                               'root_cause':f"{case['family']}/{case['control']}: emitted {finding['rule']} at {finding['path']}:{finding.get('line')} {finding.get('symbol')} has no matching oracle root/occurrence"})
            for miss in value.get('misses',[]):
                counts[(rule_for(miss['type']),miss['type'])]['fn']+=1
                d=miss['diagnostics'][0]
                reason='detector '+value['detector_error'] if value.get('detector_error') else 'no matching emitted diagnostic'
                errors.append({'case':case['id'],'repository':case['repository'],'kind':'FN','rule':rule_for(miss['type']),'type':miss['type'],
                               'root_cause':f"{case['family']}/{case['control']}: {reason} for {d['path']} {d['symbol']} ({miss['type']})"})
            for key in cells:cells[key].append({'repository':case['repository'],'eligible':value['eligible'],**counts[key]})
            attribution.extend(a['confirmed'] for a in value.get('attribution',[]) if a['confirmed'] is not None)
        labels=Counter(c['modes'][mode]['label'] for c in cases)
        per_repo={spec['id']:{'cases':sum(c['repository']==spec['id'] for c in cases),
                              'labels':dict(Counter(c['modes'][mode]['label'] for c in cases if c['repository']==spec['id']))}
                  for spec in selection['repositories']}
        results[mode]={'micro':aggregate(rows),'repo_clustered95':clustered(rows),
            'by_rule_type':{r:{t:{**aggregate(cells[(r,t)]),'repo_clustered95':clustered(cells[(r,t)])} for t in TYPES} for r in RULES},
            'by_rule':{r:{**aggregate([{**row,**{k:sum(cells[(r,t)][i][k] for t in TYPES) for k in ('tp','fp','fn')}} for i,row in enumerate(rows)])} for r in RULES},
            'labels':dict(labels),'controls_per_positive':labels['control']/labels['positive'] if labels['positive'] else None,
            'three_controls_requirement':'met' if labels['control']>=3*labels['positive'] else 'NOT MET',
            'per_repository':per_repo,'exclusions':dict(Counter(c['modes'][mode]['exclusion'] for c in cases if not c['modes'][mode]['eligible'])),
            'errors':errors,'attribution':{'labelled':len(attribution),'correct':sum(attribution),'accuracy':sum(attribution)/len(attribution) if attribution else None},
            'warning_counts':{r:sum(c['modes'][mode].get('warnings',{}).get(r,0) for c in cases) for r in ('CW003','CW004','CW005')},
            'resolved_warnings':sum(c['modes'][mode].get('resolved_warnings',0) for c in cases)}
    result={'stratum':'mutation','development_only':True,'freeze_sha256':sha(FREEZE),'selection_sha256':sha(SELECTION),
        'detector_commit':json.loads(FREEZE.read_text())['detector_commit'],'cases':len(cases),'modes':results,
        'repositories':[{k:s[k] for k in ('id','url','sha','domain')} for s in selection['repositories']],
        'case_files_sha256':{c['id']:sha(evidence/'cases'/(c['id']+'.json')) for c in cases},
        'completion':json.loads((evidence/'complete.json').read_text()),
        'limitations':['mutation prevalence is constructed, never natural or user-facing precision',
                      'copied actual-module fallback baseline augmentation explicitly flagged per case',
                      'five-branch mixes add three independent documentation branches',
                      'typed Any example inputs isolate supported name/module/arity contracts; project tests are type-checked, not executed',
                      'oracle-eligible detector execution only; excluded-case emitted noise is not estimable']}
    # Sanitized evidence asset: JSON only, stable headers, no Git alternates or
    # local repository configs. Source snapshots and patch dictionaries are in JSON.
    asset=Path.home()/'.crosswire-evidence'/'mut-v05-evidence.tgz';asset.parent.mkdir(parents=True,exist_ok=True)
    def sanitize(info):
        info.uid=info.gid=info.mtime=0;info.uname=info.gname='';return info
    with tarfile.open(asset,'w:gz') as tar:
        for directory,prefix in [(evidence,'mutation'),(root/'oracle-cache','oracle-cache')]:
            for path in sorted(directory.rglob('*.json')):
                tar.add(path,arcname=prefix+'/'+path.relative_to(directory).as_posix(),filter=sanitize)
    result['evidence']={'archive':'~/.crosswire-evidence/mut-v05-evidence.tgz','sha256':sha(asset),
                        'storage':'local sanitized archive; release upload belongs to Polaris, not performed'}
    write(ROOT/'docs/validation/mut-v05.json',result,root)
    return result


def pct(v):return 'undefined' if v is None else f'{100*v:.2f}%'
def ci(v):return 'not estimable' if v is None else f'{100*v[0]:.2f}–{100*v[1]:.2f}%'


def publish(result):
    lines=['# v0.5 mutation development corpus — Deneb','',
        '**Mutation / development only.** These numbers are never mixed with natural recorded merges, concurrent PRs or holdout data. No release acceptance is claimed. No src edits, real holdout access, sealed-file edits or project commits were performed by this task.','',
        f"The installed detector is built from Git `{result['detector_commit']}`, independently matched to its package bytes. Labels use pinned Pyright 1.1.407 and unchanged frozen M3 delta identities, before detector execution. Freeze SHA-256 `{result['freeze_sha256']}`; selection SHA-256 `{result['selection_sha256']}`. See [freeze](mut-v05-freeze.json), [selection](mut-v05-selection.json), [full aggregate](mut-v05.json).",'',
        'Repositories and sites were preregistered before builds/labels; seed `mut-v05-v1` sorts actual module-level declaration/module candidates by SHA-256. S17 prior eligible baselines inform the first three repositories; the fixed two additions were chosen by declared dependency-light structure, never mutation outcomes. No post-label replacement or apparatus tuning.','',
        '| Repository / domain | URL | SHA |','| --- | --- | --- |']
    for s in result['repositories']:lines.append(f"| {s['id']} / {s['domain']} | {s['url']} | `{s['sha']}` |")
    lines+=['','S16 templates seed real rename/delete/signature/module-move mutations and open-boundary controls. Conjunctive and repair baselines explicitly copy the original actual module for an independent fallback; these are **augmented mutation** cases, not unchanged-upstream/natural incidents or fabricated function bodies. Five-branch mixes contain the actual producer/consumer conflict plus three independent documentation edits. Typed Any example inputs isolate supported structural contracts; no runtime or project test-suite execution is claimed.','',
        'Pairwise ground truth comes from every pair; combined/plan use full integration. Fix-by-third can therefore be pairwise-positive and combined/plan-control. All participating tips need empty M3 deltas; uncertain identity/scope, external dependencies, new tip errors and textual conflicts stay unlabelled. All FP/FN records below are attributable root counts, not merely scenario counts.','']
    for mode,data in result['modes'].items():
        m=data['micro'];lines += [f'## {mode}', '',
          f"Labels: {data['labels']}; controls per positive: {data['controls_per_positive']}; ≥3 control requirement: **{data['three_controls_requirement']}**. Oracle-ineligible shares: {pct(m['unlabelled_case_share'])}; exclusions: {data['exclusions']}.",'',
          '| Rule / type | TP / FP / FN | Precision (Wilson 95%) | Recall (Wilson 95%) | Status |',
          '| --- | --- | --- | --- | --- |',
          f"| Micro | {m['tp']} / {m['fp']} / {m['fn']} | {pct(m['precision'])} ({ci(m['precision_wilson95'])}) | {pct(m['recall'])} ({ci(m['recall_wilson95'])}) | {m['sample_status']} |"]
        for rule,cells in data['by_rule_type'].items():
            for type_,v in cells.items():lines.append(f"| {rule} / {type_} | {v['tp']} / {v['fp']} / {v['fn']} | {pct(v['precision'])} ({ci(v['precision_wilson95'])}) | {pct(v['recall'])} ({ci(v['recall_wilson95'])}) | {v['sample_status']} |")
        cluster=data['repo_clustered95'];lines += ['',f"Repository-clustered 95%: precision {ci(cluster['precision'])}, recall {ci(cluster['recall'])}; eligible repositories {cluster['repositories']}. Fewer than five clusters or empty denominators is not estimable. Cells below 20 predictions/positives remain insufficient. No development gate is evaluated.",'',
             '| Repository | Cases | Labels |','| --- | ---: | --- |']
        for repo,v in data['per_repository'].items():lines.append(f"| {repo} | {v['cases']} | {v['labels']} |")
        lines += ['',f"Warnings (separate): {data['warning_counts']}; resolved warnings {data['resolved_warnings']}; attribution {data['attribution']}. CW003 warnings and migration/textual signals never enter semantic metrics.",'', 'Every FP/FN (one line per root):','']
        if not data['errors']:lines.append('None.')
        for e in data['errors']:lines.append(f"- `{e['case']}` ({e['repository']}) {e['kind']} {e['rule']}/{e['type']}: {e['root_cause']}")
    lines += ['',f"Evidence follows D-Ev1: `{result['evidence']['archive']}`, SHA-256 `{result['evidence']['sha256']}`; sanitized tar headers, portable JSON paths, no Git configuration/alternates. Only compact selection/freeze/aggregate are committed; release upload remains Polaris's responsibility. Raw source states, M3 identities, exclusions, detector output and case-level matches stay in the external asset.",'',
        'Execution uses the immutable installed wheel as a subprocess, pairwise/combined/plan with cache disabled. Protected fixture HEAD/index/refs/config/worktree snapshots are verified. Oracle dependencies are separately frozen without installed selected repositories, avoiding site-packages fallback after module movement. Original S17/M3 and sealed holdout apparatus remain untouched. Complete stability flags and evidence hashes are in the aggregate. Independent Vega sample/all-FP audit remains pending.','']
    (ROOT/'docs/validation/mut-v05.md').write_text('\n'.join(lines))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',required=True,type=Path);p.add_argument('--evidence',required=True,type=Path)
    a=p.parse_args();publish(summarize(a.evidence.resolve(),a.root.resolve()))

if __name__=='__main__':main()
