"""Record current legacy scenarios; approve only the frozen T12 transformation."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.golden_t12 import coalesce_case


def main():
    archive = json.loads((ROOT / "tests/golden/v02-pre-t12.json").read_text())
    with tempfile.TemporaryDirectory(prefix="crosswire-t12-", dir="/tmp") as temporary:
        output = Path(temporary) / "recording.json"
        env = {**os.environ, "CROSSWIRE_GOLDEN_RECORD": "1", "CROSSWIRE_GOLDEN_OUTPUT": str(output),
               "CROSSWIRE_GOLDEN_SOURCE": str(ROOT / "src"), "PYTHONPATH": str(ROOT / "src")}
        selected = [f"tests/test_{name}.py" for name in ("git", "python_analyzer", "diffing", "rules", "cli", "amendment_a1")]
        subprocess.run([sys.executable, "-m", "pytest", "-q", *selected], cwd=ROOT, env=env, check=True)
        recorded = json.loads(output.read_text())["cases"]
    before = archive["cases"]
    assert recorded.keys() == before.keys()
    changed = []
    for key in before:
        assert recorded[key] == coalesce_case(key, before[key]), f"Unapproved change: {key}"
        if recorded[key] != before[key]:
            changed.append(key)
    assert len(changed) == 9
    archive["cases"] = recorded
    archive["provenance"]["t12"] = {"command": "uv run python tests/refresh_t12_goldens.py", "changed_cases": sorted(changed)}
    (ROOT / "tests/golden/v01.json").write_text(json.dumps(archive, sort_keys=True, indent=2) + "\n")
    print("Approved 9 T12 changes; all remaining 146 golden outputs unchanged")


if __name__ == "__main__":
    main()
