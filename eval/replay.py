"""Recreate a PUBLIC case from pinned upstream source and exact patches."""
import argparse
import json
import os
from pathlib import Path
import subprocess
from .paths import resolve


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('case');parser.add_argument('--destination',type=Path,required=True);parser.add_argument('--corpus',type=Path,default=Path('eval/development/cases.json'));parser.add_argument('--source-cache',type=Path,help='Optional local upstream clone for offline replay');args=parser.parse_args()
    case=next(c for c in resolve(json.loads(args.corpus.read_text()))['cases'] if c['id']==args.case)
    if args.destination.exists():parser.error('destination must not already exist')
    env=os.environ|{'GIT_AUTHOR_NAME':'Crosswire Evaluation','GIT_AUTHOR_EMAIL':'eval@invalid','GIT_COMMITTER_NAME':'Crosswire Evaluation','GIT_COMMITTER_EMAIL':'eval@invalid','GIT_AUTHOR_DATE':'2000-01-01T00:00:00+0000','GIT_COMMITTER_DATE':'2000-01-01T00:00:00+0000','GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':os.devnull}
    def run(*arguments,input=None):return subprocess.run(['git',*arguments],cwd=args.destination,env=env,capture_output=True,input=input,check=True)
    source=str(args.source_cache) if args.source_cache else f"https://github.com/{case['repository']}.git"
    subprocess.run(['git','clone',source,str(args.destination)],env=env,capture_output=True,check=True)
    run('-c','advice.detachedHead=false','checkout','--detach',case['upstream_sha'])
    if case.get('target_patch'):
        run('apply','--index','-',input=case['target_patch'].encode())
        run('-c','commit.gpgSign=false','commit','-m','public oracle probe baseline')
    run('branch','crosswire-target','HEAD')
    for name in case['tips']:
        run('checkout','-b',name,'crosswire-target')
        patch=case.get('patches',{}).get(name,case.get(f'patch_{name}'))
        assert patch is not None, 'Missing exact branch patch'
        if patch:run('apply','--index','-',input=patch.encode())
        run('-c','commit.gpgSign=false','commit','--allow-empty','-m',f'public mutation {name}')
    print(json.dumps({'repository':str(args.destination),'target':'crosswire-target','branches':list(case['tips']),'expected_oracle_label':case['kind'],'type':case['type']}))


if __name__=='__main__':main()
