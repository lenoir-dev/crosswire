"""Record v0.4 additive metadata; reject any unapproved finding semantic changes."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.golden_v04 import project_case


def main():
    archived = json.loads((ROOT / "tests/golden/v03b-pre-v04.json").read_text())
    with tempfile.TemporaryDirectory(prefix="crosswire-v04-golden-") as temporary:
        destination = Path(temporary) / "recording.json"
        env = {**os.environ, "CROSSWIRE_GOLDEN_RECORD": "1", "CROSSWIRE_GOLDEN_OUTPUT": str(destination),
               "CROSSWIRE_GOLDEN_SOURCE": str(ROOT / "src"), "PYTHONPATH": str(ROOT / "src")}
        tests = [f"tests/test_{name}.py" for name in ("git", "python_analyzer", "diffing", "rules", "cli", "amendment_a1")]
        subprocess.run([sys.executable, "-m", "pytest", "-q", *tests], cwd=ROOT, env=env, check=True)
        recorded = json.loads(destination.read_text())["cases"]
    assert recorded.keys() == archived["cases"].keys()
    for key, value in recorded.items():
        assert project_case(key, value) == archived["cases"][key], f"Semantic change beyond additive v0.4 metadata: {key}"
    archived["cases"] = recorded
    archived["provenance"]["v04"] = {"command": "uv run --group eval python tests/refresh_v04_goldens.py",
                                    "allowed": "hint/limitations/repro and report coverage only; old findings and locations preserved"}
    (ROOT / "tests/golden/v01.json").write_text(json.dumps(archived, sort_keys=True, indent=2) + "\n")
    print("Recorded v0.4 metadata; all 155 historical output projections unchanged")


if __name__ == "__main__":
    main()
