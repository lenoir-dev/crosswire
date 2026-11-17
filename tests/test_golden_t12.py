import hashlib
import json
from pathlib import Path

from .golden_t12 import coalesce_case


def test_t12_only_actually_merged_golden_cases_change():
    folder = Path(__file__).parent / "golden"
    raw = (folder / "v02-pre-t12.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "ea112a3753c0effe5b8b68ef8009f17dd72443ef0f85da8d82e566b027260efa"
    original = json.loads(raw)["cases"]
    current = json.loads((folder / "v01.json").read_text())["cases"]
    assert current.keys() == original.keys()
    changed = []
    for key, before in original.items():
        expected = coalesce_case(key, before)
        assert current[key] == expected, f"Unapproved golden change outside T12: {key}"
        if expected != before:
            changed.append(key)
        else:
            assert current[key] == before
    assert len(changed) == 9
