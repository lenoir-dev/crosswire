# crosswire v0.4 — plan: trustworthy numbers (Python pilot) and diagnostics

Status: DRAFT (architect). Becomes frozen after v0.3b is accepted and Terra/Sol have reviewed it.
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
