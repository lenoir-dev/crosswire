"""Offline checkpoint writer only. This module has NO collection command."""
import argparse
import json
from pathlib import Path
from .checkpoint import prepare

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--policy',required=True,type=Path)
p.add_argument('--write-checkpoint',required=True,type=Path)
a=p.parse_args()
prepare(json.loads(a.policy.read_text()),a.write_checkpoint)
print('Checkpoint recorded; no metadata collected. Separate authorization still required.')
