"""Re-record only existing CW005 outputs; retain the pinned v0.1 archive."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix="crosswire-a2-", dir="/tmp") as directory:
        recording = Path(directory) / "recording.json"
        environment = {**os.environ, "CROSSWIRE_GOLDEN_RECORD": "1",
                       "CROSSWIRE_GOLDEN_OUTPUT": str(recording),
                       "CROSSWIRE_GOLDEN_SOURCE": str(ROOT / "src"),
                       "PYTHONPATH": str(ROOT / "src")}
        selected = [
            "tests/test_rules.py::test_cw005_text_conflict_once_per_path",
            "tests/test_cli.py::test_github_annotation_escapes_properties_and_message",
            "tests/test_cli.py::test_cli_no_textual_disables_conflicts",
        ]
        subprocess.run([sys.executable, "-m", "pytest", "-q", *selected], cwd=ROOT,
                       env=environment, check=True)
        path = ROOT / "tests/golden/v01.json"
        golden = json.loads(path.read_text())
        fresh = json.loads(recording.read_text())["cases"]
        refreshed = []
        for key, value in fresh.items():
            if "CW005" in json.dumps(golden["cases"][key]):
                golden["cases"][key] = value
                refreshed.append(key)
        golden["provenance"]["amendment_a2"] = {
            "policy": "Re-record CW005-containing outputs only; original recording retained in v01-original.json",
            "command": "uv run python tests/refresh_a2_goldens.py",
            "refreshed_cases": sorted(refreshed),
            "cw005_source_sha256": hashlib.sha256((ROOT / "src/crosswire/rules/cw005.py").read_bytes()).hexdigest(),
        }
        path.write_text(json.dumps(golden, sort_keys=True, indent=2) + "\n")
        print(f"Refreshed {len(refreshed)} CW005 outputs; all other outputs retained")


if __name__ == "__main__":
    main()
