"""Authorized post-label M2 scoring audit and publication; no tool reruns.

Frozen labels, raw detector bytes and original scores are retained. The primary
view applies ONLY the predeclared PY-2 module+file key, identically to mutation
and S17 journals. Vega must audit this explicit post-label correction.
"""
import argparse
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import tarfile

from benchmarks import mut_v05_m2_audit as corrected
from benchmarks.mutation_v05 import run, report
from benchmarks.s17.m3 import Identity,minimal_attribution
from benchmarks.s17.run import observation_from,files_at
from benchmarks.s17.metrics import aggregate,clustered


def raw_summary(cases,mode):
    rows=[{'repository':c['repository'],**c['modes'][mode]} for c in cases]
    for r in rows:r['detector_error']=bool(r.get('detector_error'))
    return {'micro':aggregate(rows),'repo_clustered95':clustered(rows)}


def findings(value,mode):
    raw=value.get('detector',{}).get('stdout')
    if not raw:return []
    data=json.loads(raw)
    values=[f for b in data['blocked'] for f in b['findings']] if mode=='plan' else data['findings']
    return [f for f in values if f.get('severity')=='error' and f.get('rule') in run.RULES]


def audit_mutation(root,evidence,output):
    frozen=run.verify();selection=json.loads(run.SELECTION.read_text())
    originals=[];changes=[];evidence_pins={}
    for item in selection['cases']:
        path=evidence/'cases'/(item['id']+'.json');case=json.loads(path.read_text())
        evidence_pins[item['id']]=run.sha(path);originals.append(case)
        new=deepcopy(case)
        eligible=any(v['eligible'] for v in case['modes'].values())
        if eligible:
            refs=case['oracle_refs']
            states={frozenset() if n=='target' else frozenset(n.split('+')):
                    json.loads((root/'oracle-cache'/(key+'.json')).read_text()) for n,key in refs.items()}
            baseline=states[frozenset()]['sources']
            full=max(states,key=len);integrated=states[full]['sources']
            observations={k:observation_from(v['observation']) for k,v in states.items()}
            mappings={frozenset() if n=='target' else frozenset(n.split('+')):v for n,v in case['path_maps'].items()}
            tips=set(case['rendered']['branches'])
            for mode,value in case['modes'].items():
                if not value['eligible']:continue
                diagnostics=tuple(Identity(**d) for d in value['diagnostics'])
                result=corrected.match(findings(value,mode),diagnostics,baseline,integrated,case['known_modules'])
                previous={k:value[k] for k in ('tp','fp','fn')}
                after={k:result[k] for k in previous}
                # No non-PY-2 finding or miss may be changed by this audit.
                for key in ('matches','false_positives','misses'):
                    before_other=[v for v in value[key] if v['type']!='PY-2']
                    after_other=run.normalized([v for v in result[key] if v['type']!='PY-2'],root)
                    assert before_other==after_other,(case['id'],mode,key)
                updated=new['modes'][mode]
                updated.update(after,unlabelled_predictions=len(result['unlabelled']),
                               matches=result['matches'],false_positives=result['false_positives'],
                               misses=result['misses'],unlabelled=result['unlabelled'])
                updated['attribution']=[]
                for hit in result['matches']:
                    f=hit['finding'];owner=f.get('branch');selected=set(f.get('culprits',[]))|({owner} if owner in tips else set())
                    confirmed=minimal_attribution(observations[frozenset()],observations,selected,hit['diagnostic'],mappings) if selected and selected<=tips else None
                    updated['attribution'].append({'rule':f['rule'],'confirmed':confirmed})
                assert updated['label']==value['label'] and updated['detector']==value['detector']
                if previous!=after:changes.append({'case':case['id'],'repository':case['repository'],'mode':mode,'type':'PY-2',
                    'frozen_raw':previous,'m2_corrected':after,'reason':'M2 module+file matching permits detector use line distinct from import line'})
        run.write(output/'cases'/(case['id']+'.json'),new,root)
    run.write(output/'complete.json',json.loads((evidence/'complete.json').read_text()),root)
    for identity,digest in evidence_pins.items():assert run.sha(evidence/'cases'/(identity+'.json'))==digest
    return {'case_journals':len(originals),'mode_journals':len(originals)*3,'frozen_raw':{m:raw_summary(originals,m) for m in run.MODES},
            'changes':changes,'original_case_files_sha256':evidence_pins,'relabelled_cases':0,'detector_reruns':0,'oracle_reruns':0}


def audit_s17(root):
    cases=[];changes=[];totals={k:0 for k in ('tp','fp','fn')};raw_totals=dict(totals)
    selection_pins={};evidence_pins={}
    for selection in sorted((run.ROOT/'docs/validation').glob('s17-*/selection.json')):
        selection_pins[selection.relative_to(run.ROOT).as_posix()]=run.sha(selection)
        original=selection.with_name('results.json')
        data=json.loads(original.read_text());evidence_pins[original.relative_to(run.ROOT).as_posix()]=run.sha(original)
        for case in data['cases']:
            cases.append(case)
            if not case['eligible']:continue
            repo=root/'repositories'/case['repository']
            baseline={p:s for p,s in files_at(repo,case['target'])[0].items() if p in case['scope']}
            integrated={p:s for p,s in files_at(repo,case['native_commit'])[0].items() if p in case['scope']}
            diagnostics=tuple(Identity(**d) for d in case['new_supported_diagnostics'])
            fs=case.get('detector',{}).get('report',{}).get('findings',[])
            result=corrected.match(fs,diagnostics,baseline,integrated,case['known_modules'])
            before={k:case['metrics'][k] for k in totals};after={k:result[k] for k in totals}
            for k in totals:totals[k]+=after[k];raw_totals[k]+=before[k]
            if before!=after:changes.append({'repository':case['repository'],'merge':case['merge'],'frozen_raw':before,'m2_corrected':after})
    assert len(cases)==120
    return {'stratum':'natural-development-M3','case_journals':120,'eligible_case_journals':sum(c['eligible'] for c in cases),
            'frozen_raw':raw_totals,'m2_corrected':totals,'changes':changes,'effect':'none' if not changes else 'changed scores listed',
            'relabelled_cases':0,'detector_reruns':0,'oracle_reruns':0,'selection_sha256':selection_pins,'evidence_sha256':evidence_pins}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',required=True,type=Path);p.add_argument('--evidence',required=True,type=Path)
    p.add_argument('--s17-root',required=True,type=Path);p.add_argument('--corrected-output',required=True,type=Path)
    a=p.parse_args();root=a.root.resolve();evidence=a.evidence.resolve();out=a.corrected_output.resolve()
    graph=[Path(__file__),Path(corrected.__file__),run.ROOT/'tests/test_mut_v05_m2_audit.py']
    code_pins={path.relative_to(run.ROOT).as_posix():run.sha(path) for path in graph}
    mutation=audit_mutation(root,evidence,out);s17=audit_s17(a.s17_root.resolve())
    audit={'status':'M2-only scoring correction authorized by Polaris after labelling; Vega audit pending',
           'primary':'M2-corrected metrics','contract':'matching.md M2: missing module identity + use-site file; no line/symbol/occurrence condition for PY-2',
           'matching_sha256':run.sha(run.ROOT/'docs/validation/matching.md'),'code_sha256':code_pins,
           'mutation':mutation,'s17':s17}
    run.write(run.ROOT/'docs/validation/mut-v05-m2-audit.json',audit,root)
    result=report.summarize(out,root)
    originals={json.loads(p.read_text())['id']:json.loads(p.read_text()) for p in (evidence/'cases').glob('*.json')}
    for mode,data in result['modes'].items():
        for error in data['errors']:
            case=originals[error['case']]
            if error['kind']=='FN' and error['type']=='PY-2' and mode in {'combined','plan'}:
                pair=findings(case['modes']['pairwise'],'pairwise')
                if pair and not findings(case['modes'][mode],mode):
                    error['root_cause']=(f"move_module/scenario: native module removal is found pairwise as {pair[0]['symbol']}; "
                        f"{mode} omits the removed-module use of this imported/re-exported binding (zero findings; partial coverage)")
        if mode=='pairwise':
            # Pairwise JSON has other_branch, not an explicit culprit set. The
            # frozen runner assumed culprits=[], so its attribution flags are
            # not an evaluated pairwise attribution accuracy. Do not silently
            # fix a second scoring rule under the M2-only authorization.
            data['attribution']={'status':'not evaluated: pairwise implicit other_branch was not interpreted by the frozen attribution scorer',
                                 'raw_flags_retained_in_evidence':data['attribution']}
    # Add the untouched raw journals beside corrected scoring views in D-Ev1.
    asset=Path.home()/'.crosswire-evidence/mut-v05-evidence.tgz'
    def sanitize(info):info.uid=info.gid=info.mtime=0;info.uname=info.gname='';return info
    with tarfile.open(asset,'w:gz') as tar:
        for directory,prefix in [(evidence,'frozen-raw-mutation'),(out,'m2-corrected-mutation'),(root/'oracle-cache','oracle-cache')]:
            for path in sorted(directory.rglob('*.json')):tar.add(path,arcname=prefix+'/'+path.relative_to(directory).as_posix(),filter=sanitize)
    result['evidence']['sha256']=run.sha(asset)
    result['scoring_audit']={'method':'M2-corrected primary; frozen raw side-by-side','manifest':'mut-v05-m2-audit.json',
                             'manifest_sha256':run.sha(run.ROOT/'docs/validation/mut-v05-m2-audit.json'),
                             'frozen_raw':mutation['frozen_raw'],'changes':mutation['changes'],'s17_effect':s17['effect'],'code_sha256':code_pins}
    run.write(run.ROOT/'docs/validation/mut-v05.json',result,root);report.publish(result)
    table=['## Post-label M2 scoring audit','',
           '**The inherited PY-2 scoring defect was found after labelling.** Primary metrics above implement only the predeclared M2 missing-module + use-file key. Original code, frozen labels, detector bytes and raw scores are retained; no detector or oracle run and no relabel was performed for this correction. The separately hashed/tested adapter is applied to every eligible mutation and S17 journal. Non-PY-2 matching is asserted unchanged case-by-case. Vega audit remains pending.','',
           '| Mode | Frozen raw TP / FP / FN | M2-corrected TP / FP / FN | Raw precision / recall | Corrected precision / recall |',
           '| --- | --- | --- | --- | --- |']
    for mode in run.MODES:
        raw=mutation['frozen_raw'][mode]['micro'];new=result['modes'][mode]['micro']
        counts=lambda x:' / '.join(str(x[k]) for k in ('tp','fp','fn'))
        table.append(f"| {mode} | {counts(raw)} | {counts(new)} | {report.pct(raw['precision'])} / {report.pct(raw['recall'])} | {report.pct(new['precision'])} / {report.pct(new['recall'])} |")
    table += ['',f"S17: all 120 journals reviewed with the same adapter (six eligible controls); effect **{s17['effect']}**; raw {s17['frozen_raw']} and corrected {s17['m2_corrected']}. Its original aggregate/labels/evidence are unchanged. Detailed pins, score differences and correction source/test hashes: [M2 audit](mut-v05-m2-audit.json). The correction is a transparent scoring-contract repair, not post-outcome policy selection.",'']
    table += ['Additional measurement limits: pairwise attribution is **not evaluated** because its JSON uses implicit `other_branch`, while the frozen scorer read explicit `culprits`; raw flags are retained and are not interpreted as 0% accuracy. This M2-only correction does not repair that separate attribution scorer. Five-branch mixes exercise branch count with three inert documentation branches, not five heterogeneous semantic edits. Only one conjunctive PY-5 case survived oracle eligibility; the other selected conjunctive scenarios remain excluded, with no replacement. No source or matching change is made to improve these gaps.','']
    path=run.ROOT/'docs/validation/mut-v05.md';path.write_text(path.read_text()+'\n'+'\n'.join(table))
    run.verify()
    for path,expected in code_pins.items():assert run.sha(run.ROOT/path)==expected
    print(json.dumps({'mutation_modes':{m:result['modes'][m]['micro'] for m in run.MODES},'s17_effect':s17['effect']}))


if __name__=='__main__':main()
