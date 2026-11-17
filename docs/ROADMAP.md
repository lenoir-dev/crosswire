# crosswire roadmap

Architect / acceptor: Opus 5.5 · Implementation: GPT-6.1 Terra · Tests & verification: GPT-6.1 Sol

Target: **v1.0** as defined in `docs/VISION-v1.md` (≥ 5 languages: Python, TS/JS, Go, Java, PHP;
solid analysis of ≥ 5 branches; measured quality per `docs/QUALITY.md`).

| Version | User value | Status |
| --- | --- | --- |
| v0.1 | Pairwise detector, rules CW001–CW005 | ✅ accepted (`562deeb`, 187 tests) |
| v0.2 | Harden pairwise: per-branch summaries, `--target`, cache, SARIF, GitHub Action | ✅ accepted (`75ff9d9`, 218 tests; 20 httpx PRs: 7 TP / 0 FP, all textual) |
| v0.3a | N-way: virtual integration, `check --combined`, CW006 with minimal culprit sets | ✅ accepted (`ed3c095`, 257 tests) |
| v0.3b | Safe merge order for many Python branches: `plan`, target refs, precision fixes, batched git I/O | ✅ accepted (288 tests; warm 30-branch run 4.5 s → 0.64 s). Known issue: `--combined` on Django-size repos > 180 s → v0.3.1 |
| v0.4 | Trustworthy numbers: evaluation harness, labelled Python corpus + holdout, perf baseline 5/10/30, remediation hints, JSON Schema, quickstart | planned |
| v0.5 | Second language with the same guarantees: `LanguageAdapter` core refactor + Go | planned |
| v0.6 | TypeScript / JavaScript adapter | planned |
| v0.7 | Java adapter | planned |
| v0.8 | PHP adapter | planned |
| v0.9 | Beta: planner alternatives, bounded-combinatorics hardening, full quality and perf report, independent field validation, external feedback (owner approval) | planned |
| v1.0 | Stable: every mandatory criterion of VISION-v1 §4 met | goal |

## Why pairwise is not enough for 3+ branches

Pairwise checks are neither complete nor precise once a merge set has more than two branches:

- **Conjunctive breakage (false negative).** `m.f` is defined by `def f` *and* by a guarded
  `try: from fast import f`. A deletes the `def`, B deletes the `try` import, C adds a call to
  `m.f`. Every pair is fine; {A, B, C} is broken.
- **Fixed by a third branch (false positive).** A removes `m.f`, B adds a compatibility re-export
  `m.f`, C calls `m.f`. Pair A–C is reported, yet {A, B, C} is fine — but only if B lands before
  (or together with) A.
- **Order matters.** Merge queues land branches one by one; every intermediate state of the
  target branch should be green, not just the final one.
- **Scale.** With 20–50 agent branches, O(n²) full re-analysis is wasteful; most pairs share no
  modules at all.

## v0.2 — harden pairwise (accepted)

Architect's measurements: warm cache −23 % wall time on 30 branches / 435 pairs (5.85 s → 4.5 s);
prefilter cuts semantic rule calls 1740 → 24. Remaining cost is per-pair git subprocesses →
v0.3b batches them (`git cat-file --batch`, one merge-base pass). Semantic-rule precision on real
PRs is still unmeasured (all field findings were CW005) → v0.3 validation targets repos with
refactoring PRs.

| Task | Owner | Deliverable |
| --- | --- | --- |
| A2-design | Opus | `docs/PLAN-v0.2.md` contracts: `BranchSummary`, `--target`, cache, SARIF |
| T4 summaries | Terra | refactor engine around per-branch `BranchSummary` computed once per (base, tip); readable code (one statement per line, docstrings on public functions); behaviour unchanged |
| T5 target + prefilter | Terra | `--target REF`: each branch is summarised against `merge-base(branch, target)`; pairs whose summaries cannot interact are skipped |
| T6 cache | Terra | on-disk summary cache in `$GIT_DIR/crosswire/cache/` keyed by (tool version, base, tip, roots); `--no-cache` |
| T7 outputs | Terra | `--format sarif` (SARIF 2.1.0); clear error for unknown refs; `action.yml` composite GitHub Action |
| S4 guard | Sol | regression net for the refactor: findings identical before/after on all scenarios; branch-order invariance; idempotence with/without cache |
| S5 field validation | Sol | run crosswire on a real Python project's open PR heads (`refs/pull/*/head`), triage every finding as TP/FP, record in `docs/validation/v0.2.md` |
| S6 scale benchmark | Sol | synthetic repo with 30 branches; wall time with/without cache and prefilter |
| A2-accept | Opus | review, independent run, commit |

## v0.3 — N-way

Design: `docs/design/nway.md` (D1–D8). v0.3a delivered `check --combined`; v0.3b delivers `plan`.

## Post-1.0 (optional, see VISION-v1 §4)

Intent claims before code exists and an MCP server for agents (deferred by decision V8),
OpenAPI/Protobuf contracts, C++ via `compile_commands.json`, PR-comment bot, LSP, monorepo
build graphs.

## v0.3b — backlog from the v0.3a acceptance (architect)

| Task | Owner | Item |
| --- | --- | --- |
| T9 plan | Terra | `crosswire plan` per nway.md §3 + D4–D6, D8 |
| T10 target refs | Terra | D4 part 2: re-check references already in `T` that point into modules changed in `I` |
| T11 precise CW005 culprits | Terra | a skipped branch currently lists *all* integrated branches as culprits; minimise to the branches whose changes it conflicts with |
| T12 one finding per use site | Terra | an import line and its call both produce a finding; group them per (branch, symbol, path) with the first line as location and the count in the message |
| T13 batched git I/O | Terra | one `git cat-file --batch` process and one merge-base pass per run (current wall time is dominated by subprocesses) |
| S8 plan oracles | Sol | all-orders oracle for 3–5 branch scenarios: safe steps, `together` groups, blocked reasons, stacks |
| S9 semantic field validation | Sol | real refactoring PR sets (candidates in `docs/validation/v0.2.md`); measure CW001/CW002/CW006 precision |
| A3 | Opus | review, acceptance, v0.3 release notes |
