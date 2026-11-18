import hashlib
import json
from pathlib import Path

from .golden_v04 import project_case


def test_v04_only_additive_metadata_changes_historical_outputs():
    folder = Path(__file__).parent / "golden"
    raw = (folder / "v03b-pre-v04.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "95e9ad6c7a3f39066d10712a9f0706c5397617353baa588f3d3b4bebb23b2486"
    before = json.loads(raw)["cases"]
    after = json.loads((folder / "v01.json").read_text())["cases"]
    assert before.keys() == after.keys()
    for key, value in after.items():
        assert project_case(key, value) == before[key], key
