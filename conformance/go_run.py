"""S19 renderer/oracle checks only: python -m conformance.go_run --output NEW_DIR.

The Go detector is not available until T25. Exit zero certifies only completed
oracle/template checks, never a detector pass. No detector process is reachable.
"""
import argparse
from itertools import combinations
import json
from pathlib import Path
import shutil
import tempfile

from . import git
from .go_oracle import GoOracle, validate
from .oracle import KitBug
from .render.go import NoCounterpart, render
from .run import load_cases as python_cases, digest, materialization, write, apparatus_hashes


def load_cases():
    neutral=python_cases()
    extra=[]
    for path in sorted((Path(__file__).with_name('templates')/'go').glob('*.json')):
        template=json.loads(path.read_text())
        if template['version']!=1:raise KitBug('Unsupported Go template version')
        extra.extend((path,template,c) for c in template['cases'])
    result=neutral+extra
    ids=[c['id'] for _,_,c in result]
    if len(ids)!=len(set(ids)):raise KitBug('Duplicate Go case identity')
    return result


def run_case(path,template,case,destination,oracle):
    destination.mkdir(parents=True)
    try:rendered=render(template,case)
    except NoCounterpart:
        row={'id':case['id'],'status':'no Go counterpart','detector':'not available','contract':template['contracts']['go']}
        write(destination/'result.json',row);return row
    write(destination/'rendered.json',{'template_sha256':digest(path),'case':case,'rendered':materialization(rendered)})
    with tempfile.TemporaryDirectory(prefix='crosswire-go-case-') as temporary:
        root=Path(temporary).resolve();repo=root/'repo';target,tips=git.build(repo,rendered)
        before=git.snapshot(repo);labels=list(tips);observations={}
        try:
            for size in range(len(labels)+1):
                for subset in combinations(labels,size):
                    state='+'.join(subset) or 'target';revision=git.integrate(repo,target,tips,subset)
                    files=git.files_at(repo,revision)
                    answer=oracle.check(files,root/'states'/state)
                    answer.update(commit=revision,source_sha256={p:__import__('hashlib').sha256(b).hexdigest() for p,b in files.items()})
                    observations[state]=answer
                    write(destination/'oracle.json',{'pin':'go1.27.1','states':observations},(root,'${CASE}'),(oracle.goroot,'${GOROOT}'))
            derived=validate(template,case,observations,rendered)
            if before!=git.snapshot(repo):raise KitBug('Go kit modified protected Git fixture state')
        except (KitBug,ValueError) as error:
            write(destination/'result.json',{'id':case['id'],'status':'kit-bug','reason':str(error),'detector':'not available'},(root,'${CASE}'))
            raise
    row={'id':case['id'],'status':'oracle verified; detector not available','oracle':'verified',
         'detector':'not available','contract':rendered['contract'],'expected_modes':case['expected'],
         'oracle_derived_modes':derived,'oracle_states':len(observations),'mode_checks':0}
    write(destination/'result.json',row);return row


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--go',default=shutil.which('go'),help='Pinned Go 1.27.1 executable')
    parser.add_argument('--case',action='append')
    args=parser.parse_args(argv)
    if args.output.exists():parser.error('Use a fresh output directory; evidence is never overwritten')
    args.output.mkdir(parents=True);rows=[]
    try:
        if not args.go:raise KitBug('Go unavailable; install pinned go1.27.1')
        selected=load_cases()
        if args.case:
            selected=[item for item in selected if item[2]['id'] in args.case]
            if {c['id'] for _,_,c in selected}!=set(args.case):raise KitBug('Unknown Go case ID')
        pins=apparatus_hashes()
        with tempfile.TemporaryDirectory(prefix='crosswire-go-oracle-') as temporary:
            cache=Path(temporary).resolve();oracle=GoOracle(args.go,cache)
            write(args.output/'provenance.json',{'oracle':oracle.initial,'detector':'not available','apparatus_sha256':pins},(cache,'${CACHE}'),(oracle.goroot,'${GOROOT}'))
            for path,template,case in selected:
                try:row=run_case(path,template,case,args.output/case['id'],oracle)
                except (KitBug,OSError,ValueError) as error:row={'id':case['id'],'status':'kit-bug','reason':str(error),'detector':'not available'}
                rows.append(row);print(json.dumps(row,sort_keys=True),flush=True)
            if pins!=apparatus_hashes() or oracle.provenance()!=oracle.initial:raise KitBug('Go kit/toolchain changed during run')
        failed=any(r['status']=='kit-bug' for r in rows)
        write(args.output/'summary.json',{'status':'kit-bug' if failed else 'oracle verified; detector not available',
              'detector':'not available','selection':'partial' if args.case else 'full',
              'case_count':len(rows),'no_counterpart':sum(r['status']=='no Go counterpart' for r in rows),
              'oracle_states':sum(r.get('oracle_states',0) for r in rows),'mode_checks':0,'cases':rows})
        return 2 if failed else 0
    except (KitBug,OSError,ValueError) as error:
        write(args.output/'summary.json',{'status':'kit-bug','reason':str(error),'detector':'not available','cases':rows})
        return 2


if __name__=='__main__':raise SystemExit(main())
