"""Screen real upstream targets with a full pinned checker before corpus mutation.

Run into a PRIVATE directory. Only explicitly promoted development results may
be copied to the workspace; this command prints counts, never candidate identities.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys
import time

from .oracle import run




def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-dir", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True, help="Private JSON candidate list")
    parser.add_argument("--python", required=True)
    parser.add_argument("--checker", required=True)
    args = parser.parse_args()
    args.private_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    def screen(item):
        name, roots = item
        directory = args.private_dir / name.replace("/", "--")
        if not directory.exists():
            result = subprocess.run(["git", "clone", "--depth", "1", f"https://github.com/{name}.git", str(directory)], capture_output=True)
            if result.returncode:
                return {"repository": name, "roots": roots, "eligible": False, "reason": "clone failed"}
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=directory).decode().strip()
        missing = [root for root in roots if not (directory / root).exists()]
        if missing:
            return {"repository": name, "sha": sha, "roots": roots, "eligible": False, "reason": "source root missing"}
        start = time.perf_counter()
        oracle = run(directory, roots, args.python, args.checker, timeout=120)
        row = {"repository": name, "sha": sha, "roots": roots, "eligible": oracle.status == "pass",
               "reason": oracle.reason, "seconds": time.perf_counter() - start, "oracle": asdict(oracle), "path": str(directory)}
        (directory / ".crosswire-screen.json").write_text(json.dumps(row, sort_keys=True, indent=2))
        return row

    with ThreadPoolExecutor(max_workers=3) as executor:
        rows = list(executor.map(screen, json.loads(args.candidates.read_text())))
    (args.private_dir / "screening.json").write_text(json.dumps(rows, sort_keys=True, indent=2))
    print(json.dumps({"screened": len(rows), "eligible": sum(row["eligible"] for row in rows), "details": "private"}))


if __name__ == "__main__":
    main()
