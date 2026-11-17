"""S14: persisted 54-cell × 5-run performance matrix, with explicit censoring."""

import argparse
import json
import math
import os
from pathlib import Path
import platform
import resource
import shutil
import statistics
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def percentile(values, probability):
    return sorted(values)[max(0, math.ceil(probability * len(values)) - 1)] if values else None


def worker(argv):
    from crosswire.cli import main
    import atexit
    atexit.register(lambda: print("EVAL_RSS=" + str(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss), file=sys.stderr))
    sys.argv = ["crosswire", *argv]
    raise SystemExit(main())


def sample(repo, branches, mode, timeout):
    args = ["plan" if mode == "plan" else "check", "--repo", str(repo.path), "--target", "main", "--format", "json"]
    if mode == "combined":
        args.append("--combined")
    command = [sys.executable, str(Path(__file__).resolve()), "--worker", "--", *args, *branches]
    before = repo.snapshot()
    start = time.perf_counter()
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout,
                                env={**repo.env, "PYTHONPATH": str(ROOT / "src")})
    except subprocess.TimeoutExpired:
        assert repo.snapshot() == before
        return {"seconds_lower_bound": timeout, "status": "timeout", "peak_rss": None}
    elapsed = time.perf_counter() - start
    assert repo.snapshot() == before
    if result.returncode not in (0, 1):
        return {"seconds": elapsed, "status": "error", "stderr": result.stderr[-1000:]}
    report = json.loads(result.stdout)
    rss = next((int(line.removeprefix("EVAL_RSS=")) for line in result.stderr.splitlines() if line.startswith("EVAL_RSS=")), None)
    return {"seconds": elapsed, "status": "ok", "peak_rss": rss,
            "coverage": report.get("coverage"), "limits": report.get("limits"),
            "findings": len(report.get("findings", [])), "exit": result.returncode}


def main():
    if "--worker" in sys.argv:
        worker(sys.argv[sys.argv.index("--") + 1:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--sizes", type=int, nargs="+", default=[1000, 10000, 50000])
    parser.add_argument("--branches", type=int, nargs="+", default=[5, 10, 30])
    parser.add_argument("--python-fraction", type=float, default=.1)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--vega-scenario", action="store_true", help="V3-05: 9000 Python files, 16 branches, 2 changed files per branch")
    args = parser.parse_args()
    from tests.helpers import RepoBuilder
    import hashlib
    sources = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT / "src/crosswire").rglob("*.py")}
    report = {"platform": platform.platform(), "python": sys.version,
              "git": subprocess.check_output(["git", "--version"], text=True).strip(),
              "processor": subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], text=True).strip()
                           if platform.system() == "Darwin" else platform.processor(),
              "memory_bytes": int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip())
                              if platform.system() == "Darwin" else None,
              "rss_units": "bytes" if platform.system() == "Darwin" else "KiB",
              "rss_scope": "Python worker peak RSS; not the simultaneous sum of the full process tree",
              "source_sha256": sources, "repeat": args.repeat, "timeout_seconds": args.timeout,
              "fixture": "10% Python modules (at least 30), remainder tracked text assets; independent API-body edits; textual checks enabled; no conflicts",
              "python_fraction": args.python_fraction,
              "cells": []}
    if args.resume and args.output.exists():
        previous = json.loads(args.output.read_text())
        assert previous["source_sha256"] == sources, "Cannot resume a baseline across source changes"
        assert previous["repeat"] == args.repeat and previous["timeout_seconds"] == args.timeout
        assert previous["python_fraction"] == args.python_fraction
        report = previous
    if args.vega_scenario:
        with tempfile.TemporaryDirectory(prefix="crosswire-vega-perf-") as temporary:
            repo=RepoBuilder(Path(temporary)/"repo")
            for number in range(9000):
                repo.write(f"modules/m_{number:05d}.py", "def value():\n    return 0\n")
            base=repo.commit("Vega 9000 Python files")
            labels=[]
            for number in range(16):
                label=f"feature-{number:02d}"
                repo.branch(label,base);repo.checkout(label)
                for offset in range(2):
                    repo.write(f"modules/m_{2*number+offset:05d}.py",f"def value():\n    return {number+1}\n")
                repo.commit(label);labels.append(label)
            preparation=sample(repo,labels,"plan",args.timeout)
            samples=[sample(repo,labels,"plan",args.timeout) for _ in range(args.repeat)]
            ok=[r["seconds"] for r in samples if r["status"]=="ok"]
            ready=len(ok)==args.repeat and preparation["status"]=="ok"
            report.update(fixture="Vega V3-05: 9000 tracked Python files, 16 independent branches each editing two files", budget_seconds=15,
                          cells=[{"files":9000,"python_files":9000,"branches":16,"mode":"plan","cache":"warm","warm_preparation":preparation,"samples":samples,
                                  "p50":statistics.median(ok) if ready else None,"p95":percentile(ok,.95) if ready else None,
                                  "budget":"pass" if ready and max(ok)<=15 else "fail"}])
        report["source_stable"]=sources=={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/"src/crosswire").rglob("*.py")}
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,sort_keys=True,indent=2)+"\n")
        print(json.dumps(report["cells"][0]));return
    completed = {(cell["files"], cell["branches"], cell["mode"], cell["cache"]) for cell in report["cells"]}

    def persist():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")

    with tempfile.TemporaryDirectory(prefix="crosswire-perf-matrix-", dir="/tmp") as temporary:
        for size in args.sizes:
            repo = RepoBuilder(Path(temporary) / f"repo-{size}")
            python_files = max(30, int(size * args.python_fraction))
            for number in range(size - python_files):
                repo.write(f"data/{number // 1000:03d}/{number:05d}.txt", "fixed fixture data\n")
            for number in range(python_files - 30):
                repo.write(f"source_assets/group_{number // 1000:03d}/module_{number:05d}.py", "value = 1\n")
            for number in range(30):
                repo.write(f"module_{number}.py", "def value():\n    return 0\n")
            base = repo.commit("size baseline")
            branches = []
            for number in range(30):
                branch = f"feature-{number:02d}"
                repo.branch(branch, base)
                repo.checkout(branch)
                repo.write(f"module_{number}.py", f"def value():\n    return {number + 1}\n")
                repo.commit(branch)
                branches.append(branch)
            for count in args.branches:
                for mode in ("pairwise", "combined", "plan"):
                    for temperature in ("cold", "warm"):
                        if (size, count, mode, temperature) in completed:
                            continue
                        cache = repo.path / ".git/crosswire/cache"
                        preparation = None
                        if temperature == "warm":
                            preparation = sample(repo, branches[:count], mode, args.timeout)
                        cell = {"files": size, "python_files": python_files, "branches": count, "mode": mode, "cache": temperature,
                                "warm_preparation": preparation, "samples": []}
                        for _ in range(args.repeat):
                            if temperature == "cold" and cache.exists():
                                shutil.rmtree(cache)
                            cell["samples"].append(sample(repo, branches[:count], mode, args.timeout))
                        ok = [row["seconds"] for row in cell["samples"] if row["status"] == "ok"]
                        ready = temperature == "cold" or preparation["status"] == "ok"
                        cell.update(p50=statistics.median(ok) if len(ok) == args.repeat and ready else None,
                                    p95=percentile(ok, .95) if len(ok) == args.repeat and ready else None,
                                    peak_rss_max=max((row.get("peak_rss") or 0 for row in cell["samples"]), default=0) or None,
                                    censored=sum(row["status"] == "timeout" for row in cell["samples"]))
                        report["cells"].append(cell)
                        persist()
                        print(json.dumps({key: cell[key] for key in ("files", "branches", "mode", "cache", "p50", "p95", "censored")}), flush=True)
    report["source_stable"] = sources == {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT / "src/crosswire").rglob("*.py")}
    persist()


if __name__ == "__main__":
    main()
