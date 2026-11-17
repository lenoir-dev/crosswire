"""Seal independently labelled private evidence; never execute the detector."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from .integrity import apparatus,assert_case,digest,repository_hash,verify_seal


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--private-dir',type=Path,default=Path.home()/'.crosswire-holdout/v2');p.add_argument('--labels',default='final-candidate-labels.json');p.add_argument('--output',type=Path,default=Path('docs/validation/holdout.sha256'));args=p.parse_args()
    root=Path(__file__).resolve().parents[1];private=args.private_dir
    assert not (private/'manifest.json').exists(), 'Already sealed; do not replace a seal'
    raw=json.loads((private/args.labels).read_text())
    assert len(raw)%4==0
    cases=[];exclusions=[]
    for start in range(0,len(raw),4):
        group=raw[start:start+4]
        if not all(r.get('eligible') for r in group):
            exclusions.extend(group);continue
        assert [r['kind'] for r in group]==['positive','compatible','unrelated','coordinated']
        cases.extend(group)
    repositories={r['repository'] for r in cases}
    counts=Counter('CW006' if r['type']=='PY-5' else 'CW002' if r['type']=='PY-4' else 'CW001' for r in cases if r['kind']=='positive')
    assert len(repositories)>=4, 'Not enough eligible repositories'
    assert all(counts[r]>=20 for r in ['CW001','CW002','CW006']), 'Rule cells not ready to seal'
    for case in cases:
        assert_case(case)
        case['repository_sha256']=repository_hash(case['path'])
    repository_hashes={str(i):c['repository_sha256'] for i,c in enumerate(cases)}
    (private/'repositories.json').write_text(json.dumps(repository_hashes,sort_keys=True,indent=2)+'\n')
    manifest={'status':'sealed, unmeasured; v0.5 only','retired_predecessor':'exposed; never measure','cases':cases,'excluded':exclusions,'generator_policy':json.loads((root/'eval/policy.json').read_text()),'isolation':'procedural; same OS user','apparatus':apparatus(root)}
    (private/'manifest.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
    hashes={'private/manifest.json':digest(private/'manifest.json'),'private/repositories.json':digest(private/'repositories.json'),**apparatus(root)}
    args.output.write_text(''.join(f'{sha}  {label}\n' for label,sha in sorted(hashes.items())))
    for path in [private/'manifest.json',private/'repositories.json']:path.chmod(0o600)
    private.chmod(0o700)
    verify_seal(private,root,args.output)
    (root/'docs/validation/eval-code.sha256').write_text(hashlib.sha256(json.dumps(apparatus(root),sort_keys=True,separators=(',',':')).encode()).hexdigest()+'\n')
    print(json.dumps({'status':'sealed; not measured','repositories':len(repositories),'positives_by_rule':dict(counts),'controls':sum(c['kind']!='positive' for c in cases)}))


if __name__=='__main__':main()
