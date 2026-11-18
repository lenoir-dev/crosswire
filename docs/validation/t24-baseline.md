# T24 blocked-plan baseline — Altair

2026-11-18, task `v0.5-t24-baseline`. Pre-change measurement of immutable source
`d01d5e600e856c514da0667acfa5a76241deefbd`, exported with `git archive` into an
isolated scratch directory. No checkout, source edit, cache implementation change,
search-limit change or project commit was made. The archived source hashes and
workspace source hashes are checked before/after measurement.

Apparatus: [t24_blocked_plan.py](../../benchmarks/t24_blocked_plan.py), structural
controls: [test_t24_fixture.py](../../tests/test_t24_fixture.py), complete samples,
portable Git manifests, source fingerprints and exact base64 byte captures:
[t24-baseline.json](t24-baseline.json).

## Fixtures fixed before measurement

Both contain 1,000 tracked files: 100 Python modules and 900 distinct text assets.
Thirty named branches are single-commit children of target `T`. Eight provider
modules each export `f(value)`; ten consumers per provider import and call `f(1)`.
Eleven Python fillers and a seven-region `shared.py` complete the file count.
Commits use fixed actor, timestamp, messages, SHA-1 format, sorted paths and literal
contents; `git fast-import` creates exactly the declared histories.

- **(a)** 21 safe branches, first seven editing separate assignments in `shared.py`
  with 20 comment lines separating regions; the other safe branches edit distinct
  assets. Eight branches remove separate provider functions and a final branch
  conflicts with the first shared assignment. Nine remain blocked, exceeding the
  eight-remaining group-search bound; seven same-path candidate culprits exceed
  the six-candidate cap.
- **(b)** 22 safe branches edit distinct assets, followed by the same eight
  independent function removals. Eight remaining branches enable the existing
  size-two/three group search: 28 pairs and 56 triples. No group repairs a removed
  provider. This exercises many integrated states and target first-party lookups.

The structural check uses literal edits and stdlib ASTs, with no Crosswire import
or output oracle. It verifies file counts, parent declarations, consumer/provider
contracts, safe prefix, removals, separated shared regions and conflicting value.
Tests also materialize both fixtures twice under different paths and compare all
commit IDs, and reject a hidden provider removal in the safe prefix or overlapping
shared context. Six tests pass. Product-result assertions in the runner are a
separate measurement guard; they do not define the structural labels.

## Measurement contract

Five serial timed samples per fixture/cache cell; fresh interpreter per sample,
plus one untimed preparation per warm cell. Cold clears only that fixture's
Crosswire disk cache, retaining OS pages and unreferenced Git merge objects.
Textual checks and existing search limits remain enabled. p50 is the median;
p95 is nearest rank (the maximum of five), with limited tail precision.

Worker wall time includes process startup, imports, unmodified `cli.main(plan …)`,
byte-stream capture and teardown. It excludes fixture creation, state hashing,
cache preparation and supervisor startup/metric writes. The worker imports the
archived source with `-B -S -P`; no installed Crosswire package is used. The full
supervised wall time is retained separately in every sample.

RSS gate metric is worker `RUSAGE_SELF.ru_maxrss`, matching S14. A fresh supervisor
launches exactly one worker and records `RUSAGE_CHILDREN.ru_maxrss` after waiting;
the worker separately records its waited Git children's high-water mark after
Git cleanup. Raw values are bytes on this Darwin host; MiB = bytes / 2^20. The
runner converts Linux KiB to bytes. Child high-water marks are not summed and are
not a simultaneous process-tree peak. See the [Darwin manual source](https://github.com/apple/darwin-xnu/blob/main/bsd/man/man2/getrusage.2)
and [Linux getrusage manual](https://man7.org/linux/man-pages/man2/getrusage.2.html).

Each successful sample must reproduce every stdout/stderr byte and exit status
across both cache states; canonical streams are stored losslessly in JSON.
Expected CLI exit is **1** for blocked plans, with empty stderr. Repository
HEAD/index/refs/config/logs/worktree bytes and modes are checked outside timings;
only scratch cache files and unreferenced Git objects may change. Repro commands
use relative `--repo repo`, so captures have no host directory identities.

## Predeclared post-T22–T24 budget

Before any sample, the runner fixes the same ceilings as the accepted S14
1,000-file / 100-Python-file / 30-branch / plan cells. Both stress fixtures must
meet them; no ceiling is raised to fit this baseline.

| Cache | p95 wall ceiling | Peak worker RSS ceiling |
| --- | ---: | ---: |
| cold | 2.95 s | 40.40 MiB |
| warm | 2.28 s | 30.75 MiB |

Source: [S14 measurements](v0.4.md#s14-performance-and-r3-budgets) and
[accepted per-cell budgets](../PLAN-v0.4.md#acceptance-decisions-polaris-2026-11-18).
All original S14 cells retain their own budgets and fixtures. These blocked
fixtures extend the workload beyond the original clean matrix; this run cannot
establish a regression on the original cells. Persistent acceptance breaches
require the architect's recorded decision under the existing process.

## Environment and results

Platform: `macOS-27.2-arm64-arm-64bit-Mach-O`; Apple M5; RAM 17,179,869,184 bytes. Interpreter:
`3.14.8 (main, Sep 30 2026, 17:55:09) [Clang 21.0.0 (clang-2100.3.34.2)]`; Git: `git version 2.50.1 (Apple Git-155)`.
The interpreter version matches S14; its binary SHA-256 is retained in JSON.
Load averages (1/5/15 minutes) before: **8.326/8.769/9.266**; after: **13.017/10.678/9.952**.
Other team work was active on the shared host. These are contended exploratory
baseline measurements, not quiet-machine release acceptance; no faster rerun was
selected. The 600-second apparatus timeout changes no product search bound.

| Fixture | Cache | Samples | p50 s | p95 s | Peak worker MiB | Ceiling comparison |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| a | cold | 5 | 8.659 | 8.903 | 37.86 | time fails; RSS passes |
| a | warm | 5 | 7.079 | 7.129 | 33.14 | time fails; RSS fails |
| b | cold | 5 | 19.616 | 20.499 | 62.92 | time fails; RSS fails |
| b | warm | 5 | 19.753 | 20.683 | 60.59 | time fails; RSS fails |

For every timed sample, fresh-supervisor CHILDREN peak equals worker SELF peak
exactly. Maximum worker-CHILDREN (waited Git processes) peak: **7.08 MiB**;
this is a separate child statistic, not an addition to the table's worker RSS.
All 20 samples and both untimed warm preparations exited 1 with empty stderr.
Every stdout/stderr/exit tuple matched across all ten samples and warm preparation
for its fixture. Fixture protected state, archived source, workspace source and
benchmark fingerprints remained unchanged.

| Fixture | Placed / blocked | Findings | Inexact | Coverage / limit hits |
| --- | --- | --- | ---: | --- |
| a | 21 / 9 | CW001: 80, CW005: 1 | 1 | bounded; `group_search_max_remaining`, `max_candidates` |
| b | 22 / 8 | CW001: 80 | 0 | bounded; `max_group` |

Both fixture-level `limitations` maps are empty; the inexact (a) CW005 finding
retains its per-finding search-bound/location limitations. Existing limits remain
`max_candidates: 6`, `max_group: 3`, `group_search_max_remaining: 8`.
All four proposed performance cells fail overall; only (a)/cold meets its RSS
ceiling. These pre-change failures are retained without a waiver or relaxed goal.

These ceilings are proposed acceptance goals, not a forecast that cache compaction
alone can meet them. In particular, fixture (b)'s 84 group candidates call
`planner.state()` / `analyze_combined()` and dependent `integrate._merge()` steps;
the accepted T22 independent pair-merge batching leaves that path untouched.
Profile retained `states`, `AnalysisRun.indexes`, adapter parse/module data and
integration prefix reuse before choosing T24 changes. Do not shorten searches,
drop consulted-file coverage or reintroduce cache thrashing to meet the numbers.
T23 trial counts should expose candidate evaluations separately from actual
integrations/cache hits; this baseline does not fabricate unavailable telemetry.

## Reproduction

From the repository root, with `PYTHON314` selecting Python 3.14.8 and `SCRATCH`
an empty directory outside the repository:

```sh
"${PYTHON314}" -B benchmarks/t24_blocked_plan.py --source-ref d01d5e6 \
  --work-root "${SCRATCH}" --repeat 5 \
  --output docs/validation/t24-baseline.json
PYTHONDONTWRITEBYTECODE=1 UV_OFFLINE=1 uv run pytest -q -p no:cacheprovider tests/test_t24_fixture.py
```

Explicit scratch roots are retained and must be empty; existing evidence is never
removed. Without `--work-root`, an external temporary directory is used and cleaned
afterward. JSON is incrementally persisted; timeouts are retained as lower bounds,
and incomplete cells have null quantiles rather than invented passes. A baseline
runner exit 0 means complete/stable measurement, not a performance-budget pass.
