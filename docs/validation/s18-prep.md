# S18 H1 preparation — Deneb, 2026-11-18

**Prepared for Vega audit, not authorized for the real attempt.** No real private v2 directory was opened, listed, hashed or read; no real detector/oracle measurement, source edit or project commit occurred. Polaris must commit the amendment and preregistration, Vega must audit them, T22–T24 must finish, and Polaris must separately authorize the single attempt from the immutable accepted 0.5a archive. This preparation's synthetic source snapshot is not that release freeze.

Protocol: [holdout-v2-preregistration.md](holdout-v2-preregistration.md). Successor seal: [holdout-v2-apparatus.sha256](holdout-v2-apparatus.sha256). Explicit before/after/supporting hashes: [holdout-v2-h1-amendment.json](holdout-v2-h1-amendment.json). The original `holdout.sha256` remains byte-identical. **One of its 29 public entries changes (`eval/run_holdout.py`); the other 28 public entries and both private pins are identical.** Private pins were copied from the existing public list, never rechecked against private content. Labels, generators, matching and oracle files are untouched.

H1 writes/fsyncs an exclusive private attempt marker and per-case start/result records, with 0700 directories/0600 files. Every started case is consumed even after a crash; neither a completed nor interrupted attempt can resume detector evaluation. `--report-only` binds the original sealed input bytes, frozen source/apparatus and journal identities without executing the detector or reopening case repositories. This is necessary because native merges can add unreferenced Git objects; no repository objects are removed to restore the old whole-repository hash. Initial whole-repository seal verification remains unchanged.

Release label is exactly **`0.5a`**. Micro precision can be only a **provisional pass** (point ≥95%, Wilson lower bound ≥90%, sufficient denominators), recall requires ≥80%, per-rule gates are **not evaluated**, and repository-clustered intervals are not estimable with four repositories. Any small outcome count 1–4 suppresses the entire linked statistical table, including totals, sibling cells, ratios, intervals and verdicts. Provenance and the fixed attempt status can remain public; a suppressed result makes no public gate-pass claim.

The [synthetic rehearsal summary](s18-prep-rehearsal.json), SHA-256 **`2b33436916fd0f15ae2c59d9c2ba669455a5b9b0504a550596432dc4adf7fdae`**, comes exclusively from generated private fixtures under the shared temporary directory, not from v2. Its 240 cases and 60 positives are repeated synthetic contract fixtures to exercise the plan-shaped instrument; they are **not performance estimates, independent samples or natural incidents**. S16's pinned Pyright 1.1.407 checker/runtime verifies 32 unique synthetic states first, using its Python-3.11 syntax configuration on the recorded Python-3.14 interpreter. That fixture-construction oracle is separate from unchanged v2's frozen Python-3.14 oracle/labels; no actual v2 oracle is rerun.

| Rehearsal check | Observed |
| --- | --- |
| Full seal/source/detector/matching/journal/export pipeline | 240 evaluations; synthetic TP 60, FP 0, FN 0 |
| Micro/per-rule presentation | Provisional micro precision; recall pass; each semantic rule TP 20 with no rule verdict |
| Cluster metadata | Four synthetic repositories; intervals not estimable |
| Completed attempt invoked again | Refused; still exactly 240 detector calls |
| Completed report-only | Same aggregate; zero additional detector calls |
| Abrupt second-case SIGKILL | Two durable starts; one durable result; second result absent |
| Interrupted attempt invoked again | Refused; still exactly two detector calls |
| Interrupted report-only | Status interrupted; no detector calls; small completion/failure statistics and complements suppressed |
| Injected small FP cell | Micro, all rule cells, cluster and exclusion blocks suppressed together |

Focused checks: **68 passed** (`tests/test_holdout_h1.py`, `tests/test_eval_r2.py`, `tests/test_eval.py`), including the unchanged M1/M2 regressions, gate thresholds, fsync/exclusive creation, partial-journal provenance, report-only input verification and export allowlist. The initial red run reproduced nine missing-H1 failures before implementation; no private evidence was involved. Rehearsal development also caught copied synthetic Git-index stat caches (normalized before sealing fixtures) and the post-attempt unreferenced-object/report-only issue above. Failed synthetic attempts remain private forensic evidence and never authorize retrying real v2.

Supporting code: [run_holdout.py](../../eval/run_holdout.py), [test_holdout_h1.py](../../tests/test_holdout_h1.py), [s18_rehearsal.py](../../benchmarks/s18_rehearsal.py). Rehearsal can be repeated on fresh generated fixtures; real v2 cannot. The real fail/insufficient/interrupted result must be published as-is, root-caused, and retired permanently; a new measurement needs sealed v3. No real measurement command was run in this task.
