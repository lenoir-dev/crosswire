import hashlib
import json
from pathlib import Path

from .golden_v04 import project_case


def test_v04_only_additive_metadata_changes_historical_outputs():
    folder = Path(__file__).parent / "golden"
    raw = (folder / "v03b-pre-v04.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "0946bd3495112de8ef1350e7342128324cbd586add5aaed3c8188e48f98a98dd"
    before = json.loads(raw)["cases"]
    after = json.loads((folder / "v01.json").read_text())["cases"]
    assert before.keys() == after.keys()
    for key, value in after.items():
        assert project_case(key, value) == before[key], key
