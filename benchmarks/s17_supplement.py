"""Preregister a declared supplement policy, then reuse immutable M3 measurement."""
import argparse
import json
from pathlib import Path

from benchmarks import s17_extension as driver
from benchmarks.s17 import run


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--policy',required=True,type=Path)
    parser.add_argument('--preregister',action='store_true')
    parser.add_argument('--measure',action='store_true')
    parser.add_argument('--checker-python')
    parser.add_argument('--detector-python')
    args=parser.parse_args();root=args.root.resolve();output=args.output.resolve();policy_path=args.policy.resolve()
    run.verify_freeze();policy=json.loads(policy_path.read_text())
    previous=run.ROOT/policy['previous_selection']
    if args.preregister:
        driver.CANDIDATES=[(s['id'],s['github'],s['domain'],s['roots']) for s in policy['repositories']]
        driver.RULE=policy['selection_rule']
        driver.preregister(root,output)
        path=output/'selection.json';data=json.loads(path.read_text())
        data.update(supplement_driver_sha256=run.sha(__file__),
            selection_policy=policy_path.relative_to(run.ROOT).as_posix(),selection_policy_sha256=run.sha(policy_path),
            previous_selection_sha256=run.sha(previous))
        run.write(path,data,root)
        print('Supplement policy pinned before any of its checker states',flush=True)
    elif args.measure:
        if not args.checker_python or not args.detector_python:parser.error('Both installed interpreters required')
        data=json.loads((output/'selection.json').read_text())
        assert data['supplement_driver_sha256']==run.sha(__file__)
        assert data['extension_driver_sha256']==run.sha(driver.__file__)
        assert data['selection_policy_sha256']==run.sha(policy_path)
        assert data['previous_selection_sha256']==run.sha(previous)
        run.measure(root,output,json.loads(run.POLICY.read_text()),args.checker_python,args.detector_python)
    else:parser.error('Choose --preregister or --measure')


if __name__=='__main__':main()
