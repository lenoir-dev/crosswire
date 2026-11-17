"""Run a pinned open-PR cohort without changing its checkout (PLAN-v0.2 §12.5)."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, check=True,
                          env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"}).stdout.decode().strip()


def state(repo):
    index = repo / ".git/index"
    return (git(repo, "rev-parse", "HEAD"), git(repo, "show-ref"),
            git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all"),
            index.read_bytes())


def source_hashes():
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / "src/crosswire").rglob("*.py"))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=ROOT / "docs/validation/httpx-prs.json")
    parser.add_argument("--target", default="origin/master")
    parser.add_argument("--pairwise", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    branches = [f"refs/remotes/pr/{item['number']}" for item in manifest["prs"]]
    command = [sys.executable, "-m", "crosswire", "check", "--repo", str(args.repo), "--format", "json"]
    if not args.pairwise:
        command.extend(["--target", args.target])
    command.extend(branches)
    before = state(args.repo)
    sources = source_hashes()
    start = time.perf_counter()
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    elapsed = time.perf_counter() - start
    assert state(args.repo) == before, "Field run changed HEAD/index/worktree/refs"
    assert source_hashes() == sources, "Production sources changed during the field run; rerun it"
    assert result.returncode in (0, 1), result.stderr
    report = json.loads(result.stdout)
    record = {
        "repository": manifest["repository"], "target": args.target,
        "target_sha": git(args.repo, "rev-parse", args.target),
        "mode": "pairwise" if args.pairwise else "target",
        "seconds": elapsed, "returncode": result.returncode, "stderr": result.stderr,
        "command": command, "readonly_verified": True,
        "prs": [{**item, "ref": branch, "sha": git(args.repo, "rev-parse", branch)}
                for item, branch in zip(manifest["prs"], branches, strict=True)],
        "source_sha256": sources,
        "report": report,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"seconds": elapsed, "pairs": len(report["pairs"]),
                      "findings": len(report["findings"]), "summary": report["summary"]}))


if __name__ == "__main__":
    main()
