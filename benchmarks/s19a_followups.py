"""Extend completed S19a census with its preregistered DNS cohort and fix audit.

Run after s19a_census.py; never replaces or drops a previously evaluated case.
Network remains confined to s19a_census.build_state's explicit mod-download setup.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

import s19a_census as c


def main():
    root=Path('/tmp/deneb-s19a').resolve()
    output=c.ROOT/'docs/validation/s19a-go-census.json'
    selection_path=output.with_name('s19a-go-dns-selection.json')
    selection=json.loads(selection_path.read_text())
    report=json.loads(output.read_text())
    assert 'summary' in report and len(report['cases'])==254, 'Primary run must be complete and unmodified'
    assert not any(s['repository']=='dns' for s in report['selection']), 'DNS cohort already evaluated'
    primary_hash=hashlib.sha256(output.read_bytes()).hexdigest()
    goroot=Path(subprocess.check_output([str(c.GO),'env','GOROOT'],env=c.environment(root)).decode().strip())
    names=c.code_names(goroot);helper=root/'category-helper';repo=root/'dns'
    assert c.digest(c.GO.resolve())==report['toolchain']['go_sha256']
    assert c.digest(helper)==report['toolchain']['helper_sha256']
    assert c.git(repo,'rev-parse','HEAD').decode().strip()==selection['head']
    cache={(s['repository'],s['commit']):{k:v for k,v in s.items() if k!='repository'} for s in report['states']}
    downloads={(s['go_mod_sha256'],s['go_sum_sha256']):{k:v for k,v in s.items() if k not in {'go_mod_sha256','go_sum_sha256'}} for s in report['dependency_setups']}
    report['selection'].append(selection)
    report['supplement']={'selection_sha256':c.digest(selection_path),'source_sha256':c.digest(__file__),
                          'primary_result_sha256_before_extension':primary_hash}
    start=time.monotonic()
    def save():
        report['states']=[{'repository':r,**state} for (r,_),state in cache.items()]
        report['dependency_setups']=[{'go_mod_sha256':k[0],'go_sum_sha256':k[1],**v} for k,v in downloads.items()]
        report['supplement']['seconds']=time.monotonic()-start
        temporary=output.with_suffix('.tmp')
        temporary.write_text(json.dumps(c.portable(report,root,goroot),indent=2)+'\n');temporary.replace(output)
    for index,item in enumerate(selection['merges']):
        commit,parents=item['merge'],item['parents']
        case={'repository':'dns',**item,'date':c.git(repo,'show','-s','--format=%cI',commit).decode().strip(),
              'subject':c.git(repo,'show','-s','--format=%s',commit).decode().strip()}
        merge=c.run(['git','merge-tree','--write-tree',*parents],repo,timeout=60)
        if merge['exit']==1:case.update(status='textual-conflict',classification=[])
        elif merge['exit']!=0:case.update(status='unlabelled',exclusion='merge-tree-error',merge_tree=merge)
        else:
            tree=merge['stdout'].splitlines()[0]
            bases=c.git(repo,'merge-base','--all',*parents).decode().splitlines()
            case.update(native_tree=tree,recorded_tree=c.git(repo,'rev-parse',f'{commit}^{{tree}}').decode().strip(),merge_bases=bases)
            env=__import__('os').environ|{'GIT_AUTHOR_DATE':'@0 +0000','GIT_COMMITTER_DATE':'@0 +0000'}
            integrated=subprocess.check_output(['git','-c','user.name=S19a','-c','user.email=census@example.invalid',
                'commit-tree',tree,'-p',parents[0],'-p',parents[1],'-m','S19a native integration'],cwd=repo,env=env).decode().strip()
            case['native_commit']=integrated
            states=[c.build_state(repo,p,root,helper,names,cache,downloads) for p in parents]
            merged=c.build_state(repo,integrated,root,helper,names,cache,downloads)
            case.update(parent_statuses=[s['status'] for s in states],merge_status=merged['status'],recorded_tree_matches_native=tree==case['recorded_tree'])
            case['recorded_status']=c.build_state(repo,commit,root,helper,names,cache,downloads)['status'] if tree!=case['recorded_tree'] else merged['status']
            if any(s['status']!='pass' for s in states):case.update(status='unlabelled',exclusion='non-green-parent')
            elif merged['status']=='unlabelled':case.update(status='unlabelled',exclusion=merged.get('exclusion','merge-ineligible'))
            elif len(bases)!=1:case.update(status='unlabelled',exclusion='multiple-merge-bases')
            else:
                target=c.build_state(repo,bases[0],root,helper,names,cache,downloads);case['target_status']=target['status']
                if target['status']!='pass':case.update(status='unlabelled',exclusion='non-green-target')
                elif merged['status']=='pass':case['status']='control'
                else:
                    rules=Counter(d['candidate_rule'] for d in merged['diagnostics'] if d.get('compiler_position_match') and d.get('candidate_rule'))
                    if merged.get('import_cycles'):rules['GO-8']+=len(merged['import_cycles'])
                    if merged.get('missing_packages'):rules['GO-2']+=len(merged['missing_packages'])
                    case.update(status='positive-candidate',classification=dict(rules))
                    case['interaction_diff']=c.git(repo,'diff','--stat',bases[0],tree).decode()
        report['cases'].append(case);save()
        if (index+1)%10==0:print(json.dumps({'repository':'dns','completed':index+1,'selected':len(selection['merges']),'statuses':dict(Counter(x['status'] for x in report['cases'] if x['repository']=='dns'))}),flush=True)
    # Head preflight is separate from the historical denominator. A green head
    # cannot rescue a non-green or non-module historical parent.
    report['head_preflight']=[]
    for selected in report['selection']:
        repo=root/selected['repository']
        state=c.build_state(repo,selected['head'],root,helper,names,cache,downloads)
        report['head_preflight'].append({'repository':repo.name,'commit':selected['head'],'status':state['status'],'exclusion':state.get('exclusion')})
        save()
    # Inspect the next five first-parent commits for every selected merge.
    # Fix-like titles are candidates only; they never establish a build label.
    followup_candidates=[]
    for selected in report['selection']:
        repo=root/selected['repository'];timeline=c.git(repo,'rev-list','--first-parent','--reverse',selected['head']).decode().splitlines();positions={s:i for i,s in enumerate(timeline)}
        for case in [x for x in report['cases'] if x['repository']==repo.name]:
            start_index=positions[case['merge']]+1
            following=timeline[start_index:start_index+5]
            case['followup_window']=following
            case['fix_title_candidates']=[]
            for commit in following:
                subject=c.git(repo,'show','-s','--format=%s',commit).decode().strip()
                if re.search(r'\b(fix(?:es|ed)?|build|compil\w*|import\w*)\b',subject,re.I):
                    evidence={'commit':commit,'subject':subject,'diffstat':c.git(repo,'diff','--stat',f'{commit}^',commit).decode()}
                    case['fix_title_candidates'].append(evidence)
                    followup_candidates.append((repo.name,commit))
            # Every actual clean build failure gets the same bounded follow-up
            # build audit, including failures excluded for a non-green parent.
            if case.get('merge_status')=='fail':
                case['followup_builds']=[]
                for commit in following:
                    state=c.build_state(repo,commit,root,helper,names,cache,downloads)
                    case['followup_builds'].append({'commit':commit,'status':state['status'],
                        'diagnostics':state['diagnostics'],'diffstat':c.git(repo,'diff','--stat',f'{commit}^',commit).decode()})
        save()
    report['followup_audit']={'window':'next five first-parent commits; all subjects and candidate diffstats inspected',
        'distinct_fix_title_candidates':len(set(followup_candidates)),
        'clean_merge_build_failures':sum(x.get('merge_status')=='fail' for x in report['cases']),
        'note':'Titles never supply labels; builds replayed only after a compiler-failing integration.'}
    report['dependency_snapshot']={p.relative_to(root/'modules').as_posix():c.digest(p) for p in sorted((root/'modules/cache/download').rglob('*')) if p.is_file() and not p.name.endswith('.lock')}
    report['summary']={s['repository']:dict(Counter(x['status'] for x in report['cases'] if x['repository']==s['repository'])) for s in report['selection']}
    counts=Counter()
    for case in report['cases']:
        if case['status']=='positive-candidate':counts.update(case['classification'])
    report['ranking']=[{'rule':rule,'observed_diagnostics':counts[rule],
        'status':'deferred' if rule=='GO-5' else 'observed' if counts[rule] else 'unobserved'} for rule in c.RULES]
    report['supplement']['source_stable']=c.digest(__file__)==report['supplement']['source_sha256']
    save();print(json.dumps({'summary':report['summary'],'head_preflight':report['head_preflight'],'followup_audit':report['followup_audit']}),flush=True)


if __name__=='__main__':main()
