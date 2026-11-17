"""S14: persisted 54-cell × 5-run performance matrix, with explicit censoring."""

import argparse
import json
import io
import tarfile
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


def sample(repo, branches, mode, timeout, source=None):
    args = ["plan" if mode == "plan" else "check", "--repo", str(repo.path), "--target", "main", "--format", "json"]
    if mode == "combined":
        args.append("--combined")
    command = [sys.executable, str(Path(__file__).resolve()), "--worker", "--", *args, *branches]
    before = repo.snapshot()
    start = time.perf_counter()
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout,
                                env={**repo.env, "PYTHONPATH": str(source or ROOT / "src")})
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
    parser.add_argument("--vega-scenario", action="store_true", help="R3/V4-01: 9051 files, 9000 referenced Python modules, 16 branches; all three warm budgets")
    parser.add_argument("--baseline-ref", default="89cfd99", help="R3 immutable v0.3.1 comparison source for the same fixture")
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
        baseline_sha=subprocess.check_output(['git','rev-parse',args.baseline_ref+'^{commit}'],cwd=ROOT,text=True).strip()
        report.update(fixture="Vega V4-01: 9051 tracked files, 9000 Python modules each referencing a distinct first-party module; 16 independent branches, two edited files each",
                      python_fraction=9000/9051, budget_seconds=15,
                      r3_budgets={"pairwise_max_ratio":1.2,"combined_seconds":6,"plan_seconds":15,"relative_statistics":["p50","p95"]},
                      baseline_commit=baseline_sha)
        def quantiles(samples,preparation):
            values=[r['seconds'] for r in samples if r['status']=='ok']
            ready=len(values)==args.repeat and preparation['status']=='ok'
            return {"p50":statistics.median(values) if ready else None,"p95":percentile(values,.95) if ready else None,
                    "censored":sum(r['status']=='timeout' for r in samples),
                    "peak_rss_max":max((r.get('peak_rss') or 0 for r in samples),default=0) or None}
        def persist_vega():
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
        with tempfile.TemporaryDirectory(prefix="crosswire-vega-perf-") as temporary:
            repo=RepoBuilder(Path(temporary)/"repo")
            baseline=Path(temporary)/'baseline';baseline.mkdir()
            archive=subprocess.check_output(['git','archive',baseline_sha,'src'],cwd=ROOT)
            with tarfile.open(fileobj=io.BytesIO(archive)) as content:
                content.extractall(baseline,filter='data')
            report['baseline_source_sha256']={p.relative_to(baseline).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (baseline/'src').rglob('*.py')}
            def module_source(number,value=0):
                following=f'm_{(number+1)%9000:05d}'
                return f'import {following}\n\ndef value():\n    return {value}\n\nreference = {following}.value\n'
            for number in range(9000):
                repo.write(f"m_{number:05d}.py",module_source(number))
            for number in range(51):repo.write(f'assets/{number:02d}.txt','stable asset\n')
            base=repo.commit("Vega 9051 files and 9000 first-party resolutions")
            labels=[]
            for number in range(16):
                label=f"feature-{number:02d}"
                repo.branch(label,base);repo.checkout(label)
                for offset in range(2):
                    index=2*number+offset
                    repo.write(f"m_{index:05d}.py",module_source(index,number+1))
                repo.commit(label);labels.append(label)
            preparation=sample(repo,labels,'pairwise',args.timeout,source=baseline/'src')
            baseline_samples=[sample(repo,labels,'pairwise',args.timeout,source=baseline/'src') for _ in range(args.repeat)]
            reference={"warm_preparation":preparation,"samples":baseline_samples,**quantiles(baseline_samples,preparation)}
            report['baseline_pairwise']=reference;persist_vega()
            # Plan first keeps the legacy top-level 15s budget tied to the plan cell.
            for mode in ('plan','combined','pairwise'):
                preparation=sample(repo,labels,mode,args.timeout)
                samples=[sample(repo,labels,mode,args.timeout) for _ in range(args.repeat)]
                cell={"files":9051,"python_files":9000,"branches":16,"mode":mode,"cache":"warm",
                      "warm_preparation":preparation,"samples":samples,**quantiles(samples,preparation)}
                ready=cell['p50'] is not None and cell['p95'] is not None
                if mode=='pairwise':
                    comparable=ready and reference['p50'] is not None and reference['p95'] is not None
                    cell['reference_p50']=reference['p50'];cell['reference_p95']=reference['p95']
                    cell['max_regression_ratio']=1.2
                    cell['budget']='not estimable' if not comparable else 'pass' if all(cell[k]<=1.2*reference[k] for k in ('p50','p95')) else 'fail'
                else:
                    cell['budget_seconds']=15 if mode=='plan' else 6
                    cell['budget']='pass' if ready and cell['p95']<=cell['budget_seconds'] else 'fail'
                report['cells'].append(cell);persist_vega()
                print(json.dumps({k:cell[k] for k in ('mode','p50','p95','censored','budget')}),flush=True)
        report["source_stable"]=sources=={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/"src/crosswire").rglob("*.py")}
        report['r3_budget_check']='pass' if report['source_stable'] and all(c['budget']=='pass' for c in report['cells']) else 'fail'
        persist_vega()
        raise SystemExit(0 if report['r3_budget_check']=='pass' else 1)
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
