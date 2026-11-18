"""Offline checkpoint creation or separately authorized read-only acquisition."""
import argparse
import json
from pathlib import Path
import subprocess

from .checkpoint import Permit,prepare
from .entry import acquire


def main(argv=None,*,runner=subprocess.run,transport=None):
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--acquire',action='store_true')
    mode.add_argument('--write-checkpoint',type=Path)
    parser.add_argument('--policy',type=Path)
    parser.add_argument('--predecessor',type=Path)
    parser.add_argument('--checkpoint',type=Path)
    parser.add_argument('--authorization',type=Path)
    parser.add_argument('--root',type=Path)
    args=parser.parse_args(argv)
    if args.acquire:
        if not all((args.checkpoint,args.authorization,args.root)) or args.policy or args.predecessor:
            parser.error('--acquire requires --checkpoint, --authorization, --root; policy comes only from the checkpoint')
        result=acquire(Permit(args.checkpoint,args.authorization),args.root,runner=runner,transport=transport)
        print(json.dumps({'status':result['status'],'stage':result['stage'],'get_requests':result['get_requests'],'git_bytes':result['git_bytes']}))
        return 0 if result['status']=='acquired' else 1
    else:
        if not args.policy or any((args.checkpoint,args.authorization,args.root)):
            parser.error('--write-checkpoint requires --policy only')
        prepare(json.loads(args.policy.read_text()),args.write_checkpoint,predecessor=args.predecessor)
        print('Checkpoint recorded; no metadata collected. Separate authorization still required.')
    return 0


if __name__=='__main__':raise SystemExit(main())
