"""Public live-PR noise screening, separate from labelled mutation precision."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from .paths import resolve
from .paths import locations
from .portable import portable


REPOSITORIES = [("encode/httpx", "${LIVE_HTTPX}", "master"),
                ("django/django", "${LIVE_DJANGO}", "main"),
                ("pallets/flask", "${LIVE_FLASK}", "main")]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/validation/v04-live-prs.json"))
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--offline", action="store_true", help="Replay pinned, previously fetched PR refs; no current-live claim")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    previous = json.loads(args.output.read_text()) if args.output.exists() and not args.refresh else None
    sources = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (root / "src/crosswire").rglob("*.py")}
    rows = []
    for repository, directory, default in resolve(REPOSITORIES):
        repo = Path(directory)
        if not repo.exists():
            subprocess.run(["git", "clone", f"https://github.com/{repository}.git", directory], capture_output=True, check=True)
        if previous:
            prs = next(row["prs"] for row in previous["repositories"] if row["repository"] == repository)
        else:
            prs = json.loads(subprocess.check_output(["gh", "pr", "list", "--repo", repository, "--state", "open", "--limit", "8", "--json", "number,title,headRefOid"]))
        refs = [f"refs/remotes/eval-pr/{pr['number']}" for pr in prs]
        if not args.offline:
            subprocess.run(["git", "fetch", "origin", *[f"refs/pull/{pr['number']}/head:{ref}" for pr, ref in zip(prs, refs)]], cwd=repo, capture_output=True, check=True)
        def git(*arguments):
            return subprocess.check_output(["git", *arguments], cwd=repo, env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
        before = (git("rev-parse", "HEAD"), git("for-each-ref"), git("status", "--porcelain", "-z"), (repo / ".git/index").read_bytes())
        command = [sys.executable, "-m", "crosswire", "check", "--repo", directory, "--target", "origin/" + default, "--format", "json", *refs]
        start = time.perf_counter()
        result = subprocess.run(command, capture_output=True, text=True, timeout=180, env={**os.environ, "PYTHONPATH": str(root / "src")})
        elapsed = time.perf_counter() - start
        after = (git("rev-parse", "HEAD"), git("for-each-ref"), git("status", "--porcelain", "-z"), (repo / ".git/index").read_bytes())
        assert before == after
        assert result.returncode in (0, 1), result.stderr
        report = json.loads(result.stdout)
        semantic = [finding for finding in report["findings"] if finding["rule"] not in {"CW003", "CW005"}]
        rows.append({"repository": repository, "prs": prs, "target": git("rev-parse", "origin/" + default).decode().strip(),
                     "heads": {ref: git("rev-parse", ref).decode().strip() for ref in refs}, "seconds": elapsed,
                     "command": command, "report": report, "readonly_verified": True,
                     "semantic_predictions": len(semantic), "pairs": len(report["pairs"]),
                     "potential_noise_per_100_pairs": len(semantic) / len(report["pairs"]) * 100 if report["pairs"] else None,
                     "unlabelled": [{"finding": finding, "reason": "full parent/merge oracle eligibility not established for live-PR screen"} for finding in semantic]})
    output = {"stratum": "pinned PR snapshot replay" if args.offline else "live PRs, never holdout", "repositories": rows, "source_sha256": sources,
              "source_stable": sources == {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (root / "src/crosswire").rglob("*.py")}}
    args.output.write_text(json.dumps(portable(output, locations()), sort_keys=True, indent=2) + "\n")
    print(json.dumps({"projects": len(rows), "pairs": sum(row["pairs"] for row in rows), "semantic_predictions": sum(row["semantic_predictions"] for row in rows), "source_stable": output["source_stable"]}))


if __name__ == "__main__":
    main()
