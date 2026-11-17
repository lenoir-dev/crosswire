"""Re-label historical development cases under R2's test-inclusive scope."""
from .paths import resolve
import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import json
from pathlib import Path
import tempfile

from .corpus import export
from .oracle import run,scope


def rescreen(case,python,checker):
    row=dict(case);directory=Path(case['path']);oracles={}
    with tempfile.TemporaryDirectory(prefix='crosswire-rescreen-') as temporary:
        for name,sha in [('target',case['target']),*case['tips'].items(),('integrated',case['integrated'])]:
            destination=Path(temporary)/name;export(directory,sha,destination)
            oracles[name]=asdict(run(destination,[*case['roots'],case['consumer']],python,checker))
            if name=='target' and oracles[name]['status']!='pass':break
    eligible=all(oracles.get(k,{}).get('status')=='pass' for k in ['target',*case['tips']])
    final=oracles.get('integrated',{})
    eligible &= final.get('status')=='fail' if case['kind']=='positive' else final.get('status')=='pass'
    row.update(eligible=bool(eligible),exclusion=None if eligible else 'oracle-ineligible',oracle=oracles,oracle_roots=scope(directory,[*case['roots'],case['consumer']]),oracle_positive=eligible and case['kind']=='positive',label_revision='R2 tests included')
    row['oracle_states']={'':{'status':oracles['target']['status']},**{k:{'status':oracles.get(k,{}).get('status','unlabelled')} for k in case['tips']},'+'.join(sorted(case['tips'])):{'status':final.get('status','unlabelled')}}
    # Legacy oracle configs are operational artifacts, never part of the case tree.
    (directory/'.crosswire-eval-pyright.json').unlink(missing_ok=True)
    return row


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--python',required=True);p.add_argument('--checker',required=True);p.add_argument('--corpus',type=Path,default=Path('eval/development/cases.json'));args=p.parse_args()
    data=resolve(json.loads(args.corpus.read_text()))
    with ThreadPoolExecutor(max_workers=3) as executor:rows=list(executor.map(lambda c:rescreen(c,args.python,args.checker),data['cases']))
    data['cases']=rows;data['label_revision']='R2 tests included; historical non-green targets excluded'
    args.corpus.write_text(json.dumps(data,indent=2)+'\n')
    print(json.dumps({'cases':len(rows),'eligible':sum(r['eligible'] for r in rows),'positives':sum(r['eligible'] and r['kind']=='positive' for r in rows)}))


if __name__=='__main__':main()
