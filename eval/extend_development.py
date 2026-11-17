"""Build R2 public oracle-scaffold families, retaining every failed attempt."""
from .paths import resolve
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

from .families import build
from .toolchain import verify


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--selection',type=Path,default=Path('eval/development-selection.json'));p.add_argument('--output',type=Path,required=True);p.add_argument('--python',required=True);p.add_argument('--checker',required=True);args=p.parse_args()
    verify(args.python,args.checker)
    selection=[r for r in resolve(json.loads(args.selection.read_text())) if r['repository'] in {'python-trio/sniffio','pallets-eco/blinker','pypa/trove-classifiers'}]
    jobs=[]
    for n,screen in enumerate(selection):
        for i,family in enumerate(['remove_attribute','from_import','module_move','remove_reexport','class_remove','required_keyword','unknown_keyword','too_many_positional','required_posonly','init_required','conjunctive']):
            for kind in ('positive','compatible','unrelated','coordinated'):jobs.append((screen,n,i,family,kind))
    args.output.mkdir(parents=True,exist_ok=True)
    def worker(task):
        ordinal,(screen,n,i,family,kind)=task
        evidence=args.output/f'label-{ordinal:04d}.json'
        if evidence.exists():return json.loads(evidence.read_text())
        row=build(screen,args.output/f'case-{ordinal:04d}',family,kind,i,args.python,args.checker)
        row['id']=f'r2-public-{ordinal:04d}'
        evidence.write_text(json.dumps(row,indent=2))
        return row
    with ThreadPoolExecutor(max_workers=3) as executor:rows=list(executor.map(worker,enumerate(jobs)))
    (args.output/'corpus.json').write_text(json.dumps({'cases':rows},indent=2)+'\n')
    print(json.dumps({'attempted':len(rows),'eligible':sum(r['eligible'] for r in rows),'positives':sum(r['eligible'] and r['kind']=='positive' for r in rows)}))


if __name__=='__main__':main()
