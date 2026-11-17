"""Capture public S9 PR runs, keeping corpus selection and source provenance explicit."""

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
    return subprocess.check_output(["git", *args], cwd=repo, env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"}).decode().strip()


def fingerprint():
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / "src/crosswire").rglob("*.py"))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=ROOT / "docs/validation/django-v03-prs.json")
    parser.add_argument("--mode", choices=["pairwise", "combined", "plan"], required=True)
    parser.add_argument("--target", default="origin/main")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    refs = [f"refs/remotes/pr/{item['number']}" for item in manifest["prs"]]
    target = args.target
    command = [sys.executable, "-m", "crosswire", "plan" if args.mode == "plan" else "check",
               "--repo", str(args.repo), "--target", target, "--format", "json"]
    if args.mode == "combined":
        command.append("--combined")
    command.extend(refs)
    def state():
        return [git(args.repo, "rev-parse", "HEAD"), git(args.repo, "for-each-ref", "--format=%(refname) %(objectname)"),
                git(args.repo, "status", "--porcelain=v1", "-z"), (args.repo / ".git/index").read_bytes()]
    before, sources = state(), fingerprint()
    start = time.perf_counter()
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    try:
        result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=args.timeout)
    except subprocess.TimeoutExpired:
        assert state() == before, "Timed-out field check changed HEAD/index/worktree/refs"
        record = {"repository": manifest["repository"], "mode": args.mode, "command": command,
                  "seconds": time.perf_counter() - start, "status": "timeout", "report": None,
                  "readonly_verified": True, "source_before": sources, "sources_stable": fingerprint() == sources,
                  "target": git(args.repo, "rev-parse", target)}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        print(json.dumps({"mode": args.mode, "status": "timeout", "seconds": record["seconds"]}))
        raise SystemExit(2)
    seconds = time.perf_counter() - start
    assert state() == before, "Field check changed HEAD/index/worktree/refs"
    assert result.returncode in (0, 1), result.stderr
    report = json.loads(result.stdout)
    semantic = report.get("findings", []) if args.mode != "plan" else [f for blocked in report["blocked"] for f in blocked["findings"]]
    record = {"repository": manifest["repository"], "mode": args.mode, "command": command,
              "seconds": seconds, "exit": result.returncode, "stderr": result.stderr,
              "target": git(args.repo, "rev-parse", target), "readonly_verified": True,
              "source_before": sources, "sources_stable": fingerprint() == sources,
              "prs": [{**pr, "ref": ref, "sha": git(args.repo, "rev-parse", ref)}
                      for pr, ref in zip(manifest["prs"], refs, strict=True)], "report": report}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"mode": args.mode, "seconds": seconds, "semantic_findings": sum(f["rule"] != "CW005" for f in semantic),
                      "total_findings": len(semantic), "source_stable": record["sources_stable"]}))


if __name__ == "__main__":
    main()
