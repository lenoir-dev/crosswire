"""Second preregistered supplement; no changes to the frozen oracle or identities."""
import argparse
import json
from pathlib import Path

from benchmarks import s17_extension as selection_driver
from benchmarks.s17 import run


CANDIDATES = [
    ('hpack','python-hyper/hpack','HTTP header compression',['hpack','src/hpack']),
    ('sqlparse','andialbrecht/sqlparse','SQL parsing',['sqlparse','src/sqlparse']),
    ('unidecode','avian2/unidecode','Unicode transliteration',['unidecode','src/unidecode']),
    ('six','benjaminp/six','interpreter compatibility',['six.py','src/six.py']),
    ('text-unidecode','kmike/text-unidecode','text transliteration',['text_unidecode','src/text_unidecode']),
    ('python-decouple','HBNetwork/python-decouple','configuration loading',['decouple.py','src/decouple.py']),
    ('voluptuous','alecthomas/voluptuous','data validation',['voluptuous','src/voluptuous']),
    ('jmespath','jmespath/jmespath.py','JSON query language',['jmespath','src/jmespath']),
]
RULE = ('All eight declared supplement-2 candidates, latest four reachable two-parent merges since '
        '2018-01-01 UTC with one merge-base different from both parents, a Python change and a clean '
        'native textual merge. Descending committer timestamp then SHA. Structural checks only; no '
        'oracle/detector outcome selection. Retain every selected outcome and both earlier cohorts. '
        'Chosen for small stdlib-oriented production surfaces, not observed labels. Fixed dependencies '
        'and full production/test scope remain unchanged; no promise that optional test dependencies exist.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--preregister',action='store_true')
    parser.add_argument('--measure',action='store_true')
    parser.add_argument('--checker-python')
    parser.add_argument('--detector-python')
    args=parser.parse_args();root=args.root.resolve();output=args.output.resolve()
    run.verify_freeze()
    previous=run.ROOT/'docs/validation/s17-extension/selection.json'
    if args.preregister:
        selection_driver.CANDIDATES=CANDIDATES
        selection_driver.RULE=RULE
        selection_driver.preregister(root,output)
        path=output/'selection.json';data=json.loads(path.read_text())
        data['supplement2_driver_sha256']=run.sha(__file__)
        data['previous_selection_sha256']=run.sha(previous)
        run.write(path,data,root)
        print('Supplement 2 pinned before any supplement-2 checker state',flush=True)
    elif args.measure:
        if not args.checker_python or not args.detector_python:
            parser.error('Both installed interpreters required')
        data=json.loads((output/'selection.json').read_text())
        assert data['supplement2_driver_sha256']==run.sha(__file__)
        assert data['extension_driver_sha256']==run.sha(selection_driver.__file__)
        assert data['previous_selection_sha256']==run.sha(previous)
        run.measure(root,output,json.loads(run.POLICY.read_text()),args.checker_python,args.detector_python)
    else:parser.error('Choose --preregister or --measure')


if __name__=='__main__':main()
