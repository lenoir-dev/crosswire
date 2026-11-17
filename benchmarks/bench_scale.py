"""Reproducible 30-branch cache/prefilter benchmark (PLAN-v0.2 §12.5).

Run: uv run python benchmarks/bench_scale.py --output docs/validation/scale-v0.2.json
The default excludes CW005 to isolate semantic costs; add --textual for full checks.
The unfiltered control wraps BranchSummary construction to add a shared interaction-index
sentinel. Real API/reference data remain unchanged; finding identity is asserted.
"""

from __future__ import annotations

import argparse
import atexit
from dataclasses import replace
import importlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def worker(force_prefilter_off, argv):
    from crosswire import engine
    from crosswire.cli import main as cli_main

    counters = {"summaries": 0, "semantic_rule_calls": 0}
    original = engine.BranchSummary

    def construct_summary(*args, **kwargs):
        counters["summaries"] += 1
        summary = original(*args, **kwargs)
        if force_prefilter_off:
            return replace(summary,
                           touched_modules=summary.touched_modules | {"__benchmark_interaction__"},
                           referenced_modules=summary.referenced_modules | {"__benchmark_interaction__"})
        return summary

    # Instrument construction, not private parsers or the prefilter predicate.
    engine.BranchSummary = construct_summary
    for index in range(1, 5):
        module = importlib.import_module(f"crosswire.rules.cw{index:03d}")
        original_check = module.check

        def counted(context, check=original_check):
            counters["semantic_rule_calls"] += 1
            return check(context)

        module.check = counted
    atexit.register(lambda: print("BENCH_COUNTERS=" + json.dumps(counters, sort_keys=True), file=sys.stderr))
    sys.argv = ["crosswire", *argv]
    raise SystemExit(cli_main())


def run(repo, branches, *, no_cache=False, force=False, textual=False):
    args = ["check", "--repo", str(repo.path), "--target", "main", "--format", "json"]
    if no_cache:
        args.append("--no-cache")
    if not textual:
        args.append("--no-textual")
    args.extend(branches)
    command = [sys.executable, str(Path(__file__).resolve()), "--worker"]
    if force:
        command.append("--force-prefilter-off")
    command.extend(["--", *args])
    env = {**repo.env, "PYTHONPATH": str(ROOT / "src")}
    start = time.perf_counter()
    with repo.unchanged():
        result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
    elapsed = time.perf_counter() - start
    assert result.returncode in (0, 1), result.stderr
    lines = result.stderr.splitlines()
    counters = json.loads(next(line.removeprefix("BENCH_COUNTERS=") for line in lines if line.startswith("BENCH_COUNTERS=")))
    return json.loads(result.stdout), {"seconds": elapsed, **counters}


def main():
    if "--worker" in sys.argv:
        split = sys.argv.index("--")
        worker("--force-prefilter-off" in sys.argv[:split], sys.argv[split + 1:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--branches", type=int, default=30)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--textual", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    assert args.branches >= 2 and args.repeat >= 1
    from tests.helpers import RepoBuilder

    with tempfile.TemporaryDirectory(prefix="crosswire-scale-", dir="/tmp") as temporary:
        repo = RepoBuilder(Path(temporary) / "repo")
        branches = [f"branch-{i:02d}" for i in range(args.branches)]
        for i in range(args.branches):
            repo.write(f"mod_{i}.py", "def f(x): return x\n")
        base = repo.commit("base")
        for i, branch in enumerate(branches):
            repo.branch(branch, base)
            repo.checkout(branch)
            repo.write(f"mod_{i}.py", "def f(x, y): return x + y\n")
            if i % 10 == 0:
                target = (i + 1) % args.branches
                repo.write(f"calls_{i}.py", f"import mod_{target}\nmod_{target}.f(1)\n")
            repo.commit(branch)
        cases = {}
        expected = None
        modes = [
            ("unfiltered_no_cache", {"no_cache": True, "force": True}),
            ("prefilter_no_cache", {"no_cache": True}),
            ("prefilter_cache_cold", {}),
            ("prefilter_cache_warm", {}),
        ]
        for name, options in modes:
            samples = []
            # Exactly one run is cold; subsequent default-mode runs are warm.
            repeats = 1 if name == "prefilter_cache_cold" else args.repeat
            for _ in range(repeats):
                report, sample = run(repo, branches, textual=args.textual, **options)
                if expected is None:
                    expected = report
                assert report == expected, f"Benchmark mode changed findings: {name}"
                samples.append(sample)
            cases[name] = {"samples": samples, "median_seconds": statistics.median(s["seconds"] for s in samples)}
        assert cases["unfiltered_no_cache"]["samples"][0]["semantic_rule_calls"] > cases["prefilter_no_cache"]["samples"][0]["semantic_rule_calls"], "Unfiltered control did not exercise extra rule checks"
        result = {
            "branches": args.branches, "pairs": args.branches * (args.branches - 1) // 2,
            "python": sys.version, "textual_enabled": args.textual, "cases": cases,
            "finding_count": len(expected["findings"]), "readonly_verified": True,
            "method": "separate subprocesses; cold has no prior cache; warm reuses disk; no-cache disables disk; unfiltered wraps BranchSummary construction to force shared interaction fields",
        }
        text = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text)
        print(text, end="")


if __name__ == "__main__":
    main()
