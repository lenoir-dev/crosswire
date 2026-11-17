# crosswire v0.4 — plan: trustworthy numbers (Python pilot) and diagnostics

Status: APPROVED (architect, after v0.3.1). Review notes from Terra and Sol are folded in as amendments; contracts above are binding.
User value: a user can read *measured* precision/recall for Python, see why every finding happened,
how to fix it and how to reproduce it in isolation.

## Terra — product

| Task | Deliverable |
| --- | --- |
| T14 remediation hints | Every finding gets `hint` (string or null), justified per rule: CW001 → "use `m.<rename>`" / "restore or re-export `m.f`" / "merge <fixer> first"; CW002 → the concrete call change ("pass `template=`"); CW003 → "keep one definition"; CW004 → "renumber `<path>` to `<next free number>`" / "add a merge revision"; CW005 → "rebase <branch> onto <culprits>"; CW006 → "merge <culprits> together with a compatibility shim" |
| T15 minimal reproduction | Every N-way finding gets `repro`: the exact `crosswire check --target <T> --combined <culprits..> <branch>` command line that reproduces it with only the minimal set (architect's idea: makes culprit sets actionable and verifiable by the user) |
| T16 limitations & coverage everywhere | Pairwise and combined reports gain `coverage` (`complete`/`bounded`/`partial`) and `limitations`: counts and examples of unparsable files, `unknown` resolutions, skipped splatted calls, unsupported constructs (per `docs/languages/python.md`) |
| T17 JSON Schema | `schemas/report-v1.schema.json`, `report-v2.schema.json` (Draft 2020-12), shipped in the package; `crosswire schema --version 1|2` prints them; README documents stability guarantees |
| T18 robustness | Clear errors for shallow clones (missing merge-base history), unborn branches, bare repos (supported if refs exist), submodules (ignored, noted in limitations), non-UTF-8 sources, huge files (> 2 MB skipped, noted) |
| T19 docs | Quickstart (2 minutes from install to first finding), `docs/gallery.md` with real conflict examples from the public development corpus, per-mode explanation |

## Sol — measurement (contract: `docs/QUALITY.md` + Amendment Q1, `docs/languages/python.md`)

| Task | Deliverable |
| --- | --- |
| S10 matching | `docs/validation/matching.md` predeclared one-to-one matching and recall denominator; architect approves **before** any label is collected |
| S11 harness | `eval/` package (dev-only dependency group `eval`): pinned pyright, corpus builder (mutation families on real repos with fixed seeds), oracle runner on target / tips / virtual merge, labeler, matcher, metrics (Wilson + repo-clustered bootstrap), report generator |
| S12 Python pilot corpus | ≥ 5 repositories, 30–50 positives, 3 controls per positive, mined-history candidates replayed; private holdout in `~/.crosswire-holdout/`, only `docs/validation/holdout.sha256` committed; supported types, tool versions and seeds frozen first |
| S13 pilot report | `docs/validation/v0.4.md`: dev-split debugging results, holdout aggregate metrics per rule, live-PR precision (httpx + ≥ 2 more projects), every FP and miss with root cause, empty cells reported |
| S14 perf baseline | 5/10/30 branches × small/medium/large repos × cold/warm × pairwise/combined/plan; p50/p95 wall time, peak RSS (units/platform recorded) → proposed budgets |
| S15 schema & robustness tests | every output validated against T17 schemas; T18 git-state scenarios |

## Opus — architecture and audit

Approve S10 before labelling; audit every FP and an independent 10 % of labels; set performance
budgets from S14; decide go/no-go for v0.5 (LanguageAdapter + Go) based on the pilot: if Python
precision is below the gate, v0.5 starts with fixing root causes, not with Go.

## Acceptance

All tests green on 3.11/3.14; schemas validate every golden; pilot report delivered with honest
numbers (no gate is required to pass in the pilot — the pilot exists to find out); budgets recorded.

## Inputs from the v0.3 acceptance (architect, 17:30)

1. **Oracle eligibility first.** Django's target fails pinned pyright with 28,353 errors, so it is
   ineligible as a labelled-corpus repository. S12 must screen candidates by "target passes the
   pinned oracle configuration" *before* building scenarios; prefer typed, pyright-clean
   projects (e.g. httpx, rich, attrs, pydantic-core's Python layer, black, mypy-typed libraries).
   Untyped giants (Django) remain valuable for **performance and live-PR FP screening** only.
2. **Live PRs produce almost no semantic findings** (httpx + Django: 0 non-CW005 predictions over
   25+ refactoring heads). This is expected for a conservative tool and confirms that precision
   must come from the mutation stratum; live-PR runs measure noise (FP rate per 100 PR pairs).
3. **T20 plan-reason precision:** a step must not cite "placed before X" when X is blocked
   against the target itself (conflict with `T`, independent of order). Reasons cite a deferred
   branch only if placing the step actually changes that branch's outcome.
4. **Performance reference** for S14 budgets: Django 2,943 .py files, 5 heads, cold `--no-cache`:
   combined 8.5 s, plan 8.7 s (v0.3.1, M5).

## Amendment R1 — fixes from Vega's independent review (`docs/reviews/v0.3-vega.md`)

All 13 findings are accepted into v0.4 (Altair implements, Deneb adds a regression test per finding
from Vega's reproductions). They must land **before** the pilot holdout measurement — V3-02, V3-07
and V3-08 are false positives in supported flows and would distort precision.

Order: V3-01 → V3-02/03 → V3-06/07/08 → V3-04/09 → V3-05 → V3-10/11/12/13 (V3-13 merges into T16).

Architect decisions where the review asked for one:

- **V3-01:** parse choke points treat `SyntaxError`, `RecursionError`, `ValueError` (NUL bytes on 3.11) and
  `MemoryError` as a parse failure (`unknown` + one stderr warning + a `limitations` entry). `main()` maps any
  unexpected exception to exit **2** with `crosswire: error: internal error: <type>: <msg>`; exit 1 means only
  "error findings present".
- **V3-02/03:** a module with any module-level star import (guarded included), a module-level `__getattr__`,
  or `globals()`/`sys.modules[__name__]` mutation is *open*: a missing name resolves to `unknown`, and
  `removed` API changes of such a module are suppressed (counted in `limitations` as `open-module`).
- **V3-04/09 wire form:** the target can be a culprit. `culprits` may contain the `--target` label exactly as
  given; the size-0 trial (`T + owner`) is always evaluated first; if it reproduces, `culprits = [<target>]`,
  `culprits_exact: true`, rule CW001/CW002, message "…was removed in <target>", hint "rebase <branch> onto
  <target>". `coverage: bounded` / `limits.hit` only when a limit was actually hit.
- **V3-05:** T10 candidate files = files at `T` whose imports hit a changed module (reverse index built once per
  `T`); per-state memoisation in `plan`; refs/version/root resolved once per run; ancestor relations from one
  `git rev-list`/`merge-base --independent` pass; the engine prefilter applies to combined pair loops.
  Budget for v0.4: the reviewer's 9k-file / 16-branch `plan` ≤ 15 s warm on the M5.
- **V3-06/08:** `from P import n` resolves to submodule `P/n.py` / `P/n/__init__.py` when it exists at that commit.
- **V3-07:** a deleted/renamed module file is diffed against the same *module name* at the tip, whatever file provides it.
- **V3-10:** D8 attribution (earliest containing branch) moves into `analyze_combined`.
- **V3-11:** state CW004 culprits = branches whose added files collide.
- **V3-12:** `BranchSummary.migrations` keeps only Django/Alembic paths; cache schema version bump.
- **V3-13:** folded into T16: `limitations` counts `unresolved` references by reason (third-party, open-module,
  cycle/depth, parse failure); `coverage: partial` when any supported-flow reference was unresolved.

## Amendment R2 — decisions on Vega's eval audit (`docs/reviews/v0.4-eval-vega.md`)

Taken before any holdout number exists. All 14 findings are accepted.

1. **The current holdout is retired as exposed (E4-01).** Its two repositories are recoverable from public
   files. It is never measured. The screening candidate list moves into the private directory; public files
   carry only aggregate screening counts *after* the next seal.
2. **v0.4 does not run the holdout (E4-03/E4-08).** A 6-positive, 2-repository holdout cannot decide any gate
   and would be burnt for good. The v0.4 pilot report publishes **development-split** metrics, clearly
   labelled "development data, optimistic, not a gate", plus live-PR noise rates. A new holdout is sealed in
   v0.4 for later use: ≥ 4 repositories, ≥ 20 positives per measured rule where possible, hard negatives
   (look-alike but compatible changes: optional params, re-export moves, star/`__getattr__` modules,
   package-ification, same name in another module) and a 3-branch family that exercises CW006. Its first
   measurement is the v0.5 checkpoint, after Altair's R1 fixes are frozen.
3. **Matching amendment M2 (E4-05/06/09/13), recorded in `docs/validation/matching.md`:** the supported type of a
   prediction comes from the detector's rule and symbol, not from the case; PY-2 (module move) matches on
   (module, use-site file) without a symbol; a detector crash or timeout on a positive is a **false negative**
   and also counted separately as an error; all oracle diagnostics of a positive are considered, not only the first.
4. **Integrity (E4-04/E4-10/E4-12/E4-14):** the new seal covers the case manifest, case repositories and refs,
   eval code, policy and matching rules (one hash list); `holdout.sha256`, `eval/policy.json` and the eval-code hash
   are committed by the architect before `src` is frozen; `run_holdout.py` asserts all hashes before running; the
   aggregate guard checks keys and values and suppresses cells with n < 5; node, pyright and Python deps are pinned
   with hashes; no absolute `/tmp` paths in committed configs.
5. **Oracle scope (E4-07):** screening requires the target to be green with test directories included; predictions in
   files outside the oracle scope are reported as a share, never silently dropped.
6. **E4-02 is a documented limitation:** all agents run as one OS user, so holdout isolation is procedural
   (instructions + Vega's audit), not technical. The v0.4 report states this.
7. **E4-11:** gates use the stricter of Wilson and repository-clustered bounds once ≥ 5 repositories are involved;
   below that the clustered interval is reported as "not estimable".
