# v0.4 Deneb — final validation completed

Updated 2026-11-17T20:54:55.583931+00:00. Task: `v0.4-deneb-final`.

## Current boundary

All requested Deneb validation work is complete. The report is
`docs/validation/v0.4.md`. Polaris owns acceptance, commits and publication;
independent final label audit remains a Vega/Polaris decision, not a claimed
completed audit. No project commit/checkout/stash/reset/push was performed.
No source edit or test workaround was made.

Frozen source: `6ef67da19a136f88a90b5f567255196ca78c2a94` (0.4.0).
Observed HEAD: `f234bff69d8a7f31585361591e7ec0b9a76252e2` (docs-only descendant).
`git diff 6ef67da -- src pyproject.toml uv.lock README.md` is empty.
All development/live/performance `source_stable` flags are true. Public sealed
apparatus/policy/matching/toolchain/lock inputs remain unchanged.

**Never measure either holdout in v0.4.** Only `--verify-only` was called;
result: “seal verified; not measured”. No private identities/content entered the
workspace. R2 item 2 and E4-02 procedural same-user isolation still apply.

## Completed checks and evidence

- Four authorized assertion groups fixed (annotations, permutation repro order,
  star-export unknown, actual invalid UTF-8 SkippedBlob). Resolved-by comparison
  still checks all fields and explicitly null repro.
- Guarded golden recorder: 187 passed in 62.24 s. All 155 projections equal;
  110 changed cases, 45 unchanged. `v04-golden-audit.json` inventories every
  field/suffix and T14/T16/R3 contract item, hashes all immutable archives.
  No projection broadening; A2/T12/v0.4 guards passed in both full suites.
- Python 3.11.17: 446 passed, 0 failed/skipped, 391.08 s.
- Python 3.14.8: 446 passed, 0 failed/skipped, 406.96 s.
  Exact commands, interpreter/source provenance and suite output:
  `v04-checks.json`. The two suites ran concurrently; their elapsed times are
  not isolated performance observations.
- Development: 228 attempted / 179 eligible / 44 positives / 135 controls;
  TP44 FP0 FN0, detection precision/recall 100%, micro Wilson 95% 91.9704–100%.
  Exact labelled attribution 44/44; errors0; outside-scope predictions0/44;
  excluded49/228 (21.4912%). Only three eligible repositories; all clustered
  intervals are not estimable. **Development data, optimistic, not a gate.**
  CW001 TP20, CW002 TP21, CW006 TP3; all FP/FN zero. CW006 and most supported
  types remain insufficient. PY-6/CW004 and non-Python cells are unmeasured.
- Historical declaration mutations: 47 eligible / 11 positive / 36 controls.
  API oracle scaffolds: 132 eligible / 33 positive / 99 controls. The latter
  are wrappers around upstream API objects, not natural incidents.
- Four CW002 reason disagreements (17/21 agreement): positional-only keyword
  use versus Pyright “Expected 1 more positional argument”, frozen categorizer
  null. Entries/root causes retained in `v04-development-breakdown.json` and
  report. No eligible FP or miss exists to diagnose. Coverage:116 complete,
  63 partial. Do not infer whole-program coverage from the matching result.
- Fresh 18-case seeded public R2/r6 audit sample:
  `v04-final-audit-sample.json`. Prepared only; not independently audited.
  Old `v04-development-audit-sample.json` remains historical evidence.
- PR preflight verified HTTPX/Django/Flask target and all old PR head SHAs.
  Pinned snapshot replay:19 heads / 59 pairs / 0 semantic predictions;
  six CW005 textual findings and zero CW003 warnings. Read-only verified.
  All pairs are oracle-unlabelled, so no semantic precision claim. Evidence:
  `v04-live-preflight.json`, `v04-live-prs.json`.

## S14 and R3

Both timing jobs ran serially, only after all Deneb tests/oracles/evaluations.
No reruns or selected fast samples. Exact commands, UTC bounds, exits, load
and process-executable CPU observations: `v04-perf-environment.json`.

Matrix: 54 cells × 5 = 270 samples;
0 censored. 1k/10k/50k files,10% Python;
5/10/30 branches; pairwise/combined/plan; cold/warm disk cache.
`v04-perf-matrix.json` retains every sample/warmup/coverage/search limit/RSS.
All matrix samples report complete coverage; search hit flags are empty.
Actual trial counts / --max-trials are not exposed by frozen source: unavailable
telemetry against QUALITY §4, not inferred from empty hit flags.
Quantiles require all samples plus warmup where applicable. Peak RSS is the
Python worker only, bytes on Darwin; report tables convert to MiB. This is
not summed process-tree RSS. Platform/hardware/interpreter are recorded.

R3 fixture:9,051 files / 9,000 distinct first-party-referencing Python modules /
16 independent branches editing two files each. Baseline commit
`89cfd99e7804c4a761223f4d12f5f7e9b825c581` exported read-only with git archive.
Baseline warm pairwise p50=2.167242,p95=2.177592 s.

| Current mode | p50 s | p95 s | R3 status |
| --- | ---: | ---: | --- |
| plan | 2.439898 | 2.475087 | pass |
| combined | 1.874150 | 1.884499 | pass |
| pairwise | 2.354558 | 2.381094 | pass |

Overall R3: **pass**, benchmark exit 0.
Pairwise p50 AND p95 must be <=1.2× baseline; combined p95<=6s;
plan p95<=15s. No hidden waiver. The report proposes next-release per-cell
1.10× p95/RSS budgets on this platform; Polaris must accept or adjust them.

## Acceptance handoff / what remains for Polaris

1. Read `v0.4.md` and evidence; decide pilot acceptance and any R3 budget issue.
2. Independently audit final public labels (18-case sample, empty FP set).
3. Accept/adjust S14 platform-specific future budgets explicitly and address
   the unavailable trial-count telemetry in acceptance.
4. Preserve v2 holdout seal for separately authorized v0.5 measurement. Do not
   run it to complete v0.4 or tune to its content.
5. Commit/publish owned work. Pre-existing untracked
   `docs/design/v0.4-review-sol.md` and `docs/design/v0.4-review-terra.md` were
   left untouched; distinguish them from Deneb's files.

Final commands are recorded in `v04-checks.json` and performance environment
artifact. To regenerate base report use `python -m eval.publish`; it requires
manual review/completion of R3 budgets, provenance, exclusions/coverage,
per-stratum/type metrics, audit status and cohort SHAs, all present in final
`v0.4.md`. Do not replace the completed report with its incomplete boilerplate.
