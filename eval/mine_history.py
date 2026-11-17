"""Replay mined real merge candidates; messages alone never create positive labels."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import tempfile
import random
from .paths import resolve

from .corpus import export, git
from .oracle import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--checker", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    rows = []
    for screen in resolve(json.loads(args.selection.read_text())):
        repo = Path(screen["path"])
        if git(repo, "rev-parse", "--is-shallow-repository") == "true":
            subprocess.run(["git", "fetch", "--unshallow"], cwd=repo, capture_output=True, check=True)
        commits = git(repo, "log", screen["sha"], "--merges", "--format=%H").splitlines()
        random.Random(17042026).shuffle(commits)
        commits=commits[:args.limit]
        for commit in commits:
            parents = git(repo, "show", "-s", "--format=%P", commit).split()
            if len(parents) != 2:
                continue
            base = git(repo, "merge-base", *parents)
            merge = subprocess.run(["git", "merge-tree", "--write-tree", *parents], cwd=repo, capture_output=True, text=True)
            entry = {"repository": screen["repository"], "merge": commit, "parents": parents, "base": base,
                     "textually_clean": merge.returncode == 0, "label": "unlabelled", "oracles": {}}
            if merge.returncode == 0:
                # Test the native merge-tree, not an upstream merge commit containing hidden fixes.
                tree = merge.stdout.splitlines()[0]
                with tempfile.TemporaryDirectory(prefix="crosswire-mined-", dir="/tmp") as temporary:
                    for label, sha in [("target", base), ("parent1", parents[0]), ("parent2", parents[1]), ("integrated", tree)]:
                        root = Path(temporary) / label
                        export(repo, sha, root)
                        entry["oracles"][label] = asdict(run(root, screen["roots"], args.python, args.checker))
                parent_status = [entry["oracles"][label]["status"] for label in ("target", "parent1", "parent2")]
                final = entry["oracles"]["integrated"]["status"]
                if parent_status == ["pass"] * 3 and final == "pass":
                    entry["label"] = "control"
                elif parent_status == ["pass"] * 3 and final == "fail":
                    entry["label"] = "candidate-positive-needs-attribution"
                else:
                    entry["reason"] = "non-green parent/target or checker environment failure"
            else:
                entry["reason"] = "textual conflict"
            rows.append(entry)
    args.output.write_text(json.dumps(rows, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"replayed_candidates": len(rows), "controls": sum(row["label"] == "control" for row in rows),
                      "candidate_positives": sum(row["label"] == "candidate-positive-needs-attribution" for row in rows)}))


if __name__ == "__main__":
    main()
