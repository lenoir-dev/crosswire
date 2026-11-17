# crosswire roadmap

Architect / acceptor: Opus 5.5 · Implementation: GPT-6.1 Terra · Tests & verification: GPT-6.1 Sol

| Version | Theme | Status |
| --- | --- | --- |
| v0.1 | Pairwise detector, rules CW001–CW005 | ✅ accepted (`562deeb`, 187 tests) |
| v0.2 | Harden pairwise + groundwork for N-way (per-branch summaries, target ref, cache, SARIF, GitHub Action) | ✅ accepted (218 tests, field run on 20 httpx PRs: 7 TP / 0 FP) |
| v0.3a | N-way: virtual integration, `check --combined`, CW006 with minimal culprit sets | 🔄 in progress (design approved: `docs/design/nway.md` D1–D8) |
| v0.3b | `crosswire plan` merge order, target-reference re-check, stacked branches, batched git I/O | next |
| v0.4 | Agent-native: intent claims before code exists, orchestrator hook / MCP server | idea |
| v0.5 | More languages (TypeScript/JS, Go) behind optional extras | idea |

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

## v0.3 — N-way (next)

See `docs/design/nway.md`. Headline features: `crosswire check --combined` (analyse the virtual
merge of the whole set), new rule **CW006 combined-break** with a *minimal culprit set*,
`resolved_by` annotations on pairwise findings that a third branch fixes, and
`crosswire plan` — a merge order / batches in which every intermediate state is clean.

## v0.4 — agent-native (later)

- **Intent claims:** before an agent writes code, the orchestrator registers the symbols it plans
  to change (`crosswire claim --branch X billing.charge`); crosswire warns when two live claims
  collide or when a claim breaks references added on other branches — conflicts are caught
  *before* any work is wasted.
- `crosswire serve --mcp` so coding agents can query "is it safe to change `billing.charge`?".
- Paradev / CI integration recipe: re-check all live agent branches on every push.
