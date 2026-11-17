# crosswire v0.3b — frozen plan (merge plan, target references, precision)

Status: APPROVED. Builds on PLAN.md, PLAN-v0.2.md, PLAN-v0.3a.md and `docs/design/nway.md`
(D4–D6, D8 are implemented here). Ownership and git rules unchanged (Terra: `src/**`,
`README.md`, `action.yml`; Sol: `tests/**`, `benchmarks/**`, `docs/validation/**`; nobody commits).
Work order for Terra: T12 → T11 → T10 → T9 → T13. Sol: tests for each task as it lands, then S8, S9.

## T12 — one finding per use site (all modes)

Findings with the same `(rule, branch, other_branch | culprits, path, symbol)` are merged into one:
location = the smallest line, message unchanged when there is one use, otherwise suffixed
`` (N uses in this file) ``. JSON gains no new keys. Golden snapshots are re-recorded only for
cases whose findings actually merge (Sol proves the rest unchanged, as in A2).

## T11 — precise culprits for skipped branches

For a branch `X` skipped by `integrate`, candidates = branches integrated before it whose changed
paths intersect `X`'s conflicted paths, in merge order. Enumerate subsets by size 1..3, then
sorted labels, over ≤ 6 candidates: the first subset `S` with `merge(T + S, X)` conflicting is
the culprit set (`culprits_exact: true`); else all candidates, `culprits_exact: false`.

## T10 — target references (D4 part 2)

After integration, for every `.py` file in `I` that imports a module whose file differs between
`T` and `I`: references in that file that also exist (same `(path, module, name, call)` multiset
entry) in `T`'s version of the file are **target references**. Each one that is `valid` in `T` and
broken in `I` (same rules as v0.3a §3.2) is reported with `branch` = the `--target` label as given
and culprits enumerated over the integrated branches that changed the consulted files
(owner = none: trials are `T + S`). Rule id: CW001/CW002 for one culprit, CW006 otherwise.

## T9 — `crosswire plan`

`crosswire plan --target T [--src ..] [--format text|json] [--no-cache] B1 .. Bn` (n ≥ 1).

- **State findings** of an ordered set `P` = v0.3a combined findings of `P` (incl. CW005 skips) +
  T10 target references + **state CW003** (two branches in `P` added different definitions of one
  qualname in one module; warning) + **state CW004** (in `I(P)`: two migration files with the same
  number in one Django `migrations/` dir where at least one was added by a branch in `P`; or two
  Alembic revisions sharing a `down_revision` where at least one was added by a branch in `P`; error).
- **Keys** (D5): `(rule, path, symbol or path)`. Errors present at `T` alone never count. A step is
  clean iff `error_keys(P + step) ⊆ error_keys(P)`.
- **Order constraints** (D8): if `Bi` is an ancestor of `Bj` (both in the set), `Bi` must be placed
  before `Bj`; `contained_in[Bi] = [Bj, ..]` (sorted). A contained branch is placed normally; its
  changes are not double-counted because integration already includes them.
- **Greedy** (nway.md §3): first clean single branch in user order (respecting constraints) →
  step `{branches: [X], together: false}`; else the first clean group of size 2 then 3 over the
  remaining branches (combinations in user order), only if ≤ 8 branches remain → step
  `{branches: [...], together: true}` (D6: only the state after the whole group is judged); else
  every remaining branch is `blocked` with the new error findings it would introduce on the
  current state (one entry per branch, findings as JSON v2 objects). Stop.
- **Output.** text:
  ```
  Merge plan into <target> (<n> branch(es)):
    1. feat-a
    2. feat-b + feat-c   (merge together)
  Blocked:
    feat-d: app/x.py:3 CW006 `m.f` is broken after merging {...}
  ```
  JSON: `{"version": 2, "tool": "crosswire", "mode": "plan", "target": "<sha>",
  "steps": [{"branches": [..], "together": bool}], "blocked": [{"branch": .., "findings": [..]}],
  "contained_in": {..}, "summary": {"placed": n, "blocked": m}}`. Exit 0 if `blocked` is empty,
  else 1; usage/git errors 2.

## T13 — batched git I/O

One long-lived `git cat-file --batch` process per repo for blob reads (existence from the
`missing` reply), memoised `list_files` and `merge_base`. Findings must be identical; target:
≥ 30 % faster than the v0.2 warm-cache benchmark (4.5 s, 30 branches, 435 pairs).

## Verification (Sol)

- Tests for T10–T13 against this plan (T12 golden proof; T11 exact/inexact; T10 a caller that
  exists only in `T`; T13 identity + benchmark JSON `docs/validation/scale-v0.3.json`).
- **S8 plan oracles:** for 3–5 branch scenarios, brute-force all orders with `check --combined` on
  every prefix as the oracle; assert that `plan`'s steps produce only clean prefixes, that
  fix-before-removal is ordered (B before A in "fixed by third branch"), that a pair which is clean
  only together becomes a `together` step, blocked reasons, stacks (`contained_in`), determinism.
- **S9 semantic field validation:** a real repository with refactoring PRs (candidates from
  `docs/validation/v0.2.md`), run pairwise, `--combined` and `plan`; triage every non-CW005
  finding TP/FP → `docs/validation/v0.3.md` with precision per rule.

## Acceptance (architect)

All tests green on 3.11 and 3.14; architect scenarios (`/tmp/cw-nway`: conjunctive, fix-by-third,
textual skip) produce: plan places S before R, A/B/C blocked or ordered per oracle; benchmark target met.

## Amendment B1 (architect, aligning with VISION-v1 before dispatch)

- **Explanations (V1 §4.1):** every plan step gets `reason` (one sentence: why it is safe at this
  point, e.g. "no new errors; resolves CW001 of feat-c" or "clean only together: each alone breaks
  `m.f`"); every blocked entry gets a `hint` when one is justified (e.g. "merge feat-b first").
- **Coverage (V7):** `plan` and `check --combined` JSON gain top-level `coverage`
  (`"complete"` | `"bounded"`) and `limits` (`{"max_candidates": 6, "max_group": 3,
  "group_search_max_remaining": 8, "hit": [..]}`); text output prints one line when bounded:
  `Coverage: bounded (<which limit>) — unchecked combinations are not proven safe.`
