"""Confirm the pinned build's rejection of every preflight-excluded module state.

Run after the primary census and followup extension, without changing labels.
No dependency download or other network call occurs here.
"""
import json
from pathlib import Path
import time

import s19a_census as c


def main():
    root=Path('/tmp/deneb-s19a').resolve()
    output=c.ROOT/'docs/validation/s19a-go-census.json'
    report=json.loads(output.read_text())
    assert 'followup_audit' in report, 'Wait until the followup extension finishes'
    assert 'context_audit' not in report, 'Audit already complete'
    env=c.environment(root)
    goroot=Path(c.run([str(c.GO),'env','GOROOT'],root,env)['stdout'].strip())
    start=time.monotonic();count=0
    for state in report['states']:
        if state.get('exclusion')!='no-root-module':continue
        repo=root/state['repository'];directory=root/'context-audit-state'
        c.snapshot(repo,state['commit'],directory)
        assert not (directory/'go.mod').exists()
        build=c.run([str(c.GO),'build','-gcflags=-e','./...'],directory,env)
        assert build['exit'] not in (None,0), 'Unexpected context or timeout; do not silently change labels'
        state['build']=build
        state['context_rejection_confirmed']=True
        count+=1
        if count%100==0:print(f'confirmed offline module-context exclusions {count}',flush=True)
    report['context_audit']={'states':count,'source_sha256':c.digest(__file__),'seconds':time.monotonic()-start,
                             'note':'Explicit offline build executed after original preflight exclusion; no module files invented and no labels changed'}
    report['completion']={'status':'complete','selected_merges':len(report['cases']),
                         'state_count':len(report['states']),'all_clean_state_builds_recorded':all('build' in s for s in report['states']),
                         'go_binary_unchanged':c.digest(c.GO.resolve())==report['toolchain']['go_sha256'],
                         'compiler_unchanged':c.digest(goroot/'pkg/tool/darwin_arm64/compile')==report['toolchain']['compile_sha256'],
                         'clone_heads_unchanged':all(c.git(root/s['repository'],'rev-parse','HEAD').decode().strip()==s['head'] for s in report['selection'])}
    assert all(report['completion'][k] for k in ('all_clean_state_builds_recorded','go_binary_unchanged','compiler_unchanged','clone_heads_unchanged'))
    output.write_text(json.dumps(c.portable(report,root,goroot),indent=2)+'\n')
    print(json.dumps(report['completion']),flush=True)


if __name__=='__main__':main()
