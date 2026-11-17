# Design: N-way analysis (v0.3) — APPROVED (decisions D1–D8 below override the draft text)

Author: Opus 5.5. Reviewers: Terra (implementability), Sol (testability).
Depends on v0.2: `BranchSummary`, `--target`, cache.

## Model

- **Target** `T` — the branch everything lands in (e.g. `main`). Required in N-way mode.
- **Merge set** `S = [B1..Bn]`, in the order given by the user (that order is the default merge order).
- **Integrated state** `I(S')` for any ordered subset `S'`: the virtual result of merging the
  branches of `S'` into `T` one by one.

## 1. Virtual integration

`C0 = T`; for each `Bi`: `tree = git merge-tree --write-tree C(i-1) Bi`; on success
`Ci = git commit-tree tree -p C(i-1) -p Bi -m crosswire-virtual` (loose objects only, no refs —
still within the read-only rule). On textual conflict `Bi` is reported as CW005 against the
integrated state and **excluded** from the rest of the integration (recorded in `skipped`).
Virtual commits are cached by `(C(i-1), Bi)`.

## 2. Combined check — `crosswire check --target T --combined B1 .. Bn`

On the final integrated state `I`:

1. **Added references** of every integrated branch `X` (from its `BranchSummary`) are resolved
   against the symbol table of `I` (modules read from `I`, A1 rules: imports, guarded
   definitions). A reference is **broken in I** if its module is missing, the name is undefined,
   or its call does not bind to the signature in `I` — and it was *not* broken at `X`'s tip
   (pre-existing breakage is never blamed on the merge).
2. **Existing references** in `T` are re-checked only for target modules whose symbol table in
   `I` differs from `T` (reverse index `module → referencing files at T`). This catches
   conjunctive removals where nobody added a reference.
3. Every broken reference becomes **CW006 combined-break (error)**, with a **minimal culprit set**:
   candidates are the branches that changed the target module's file (or a file it re-exports
   from); minimise with ddmin over the candidates, re-integrating only those (usually 1–3
   branches). Message: `` `m.f` is undefined after merging {A, B}; neither branch alone removes it ``.
   When the culprit set has size 1, the finding is the same as pairwise CW001/CW002 and is
   reported under that rule instead (no double reporting).
4. Pairwise findings (CW001–CW004) are still computed. If the flagged reference is fine in `I`,
   the finding is downgraded to `warning` and gets `resolved_by: [branches]` = the minimal set
   whose changes make it valid (ddmin as above). The fix is real only if the order respects it —
   `plan` enforces that.

## 3. Merge plan — `crosswire plan --target T B1 .. Bn`

Greedy and deterministic:

```
state = T; remaining = S (user order); steps = []
while remaining:
    pick the first X in remaining such that integrating X into state yields no new
        error findings (CW005/CW006/CW001-4 evaluated on state + X)        -> step [X]
    else the smallest group G (|G| <= 3, user order, lexicographic tie-break) that is
        clean only when integrated together                                -> step G ("merge together")
    else: mark the rest as blocked, with the findings that block each one; stop
    state = state + step
```

- **Stacked branches:** if `Bi` is an ancestor of `Bj`, `Bi` must come first; if `Bj` contains
  all of `Bi`, `Bi` is reported as `superseded_by: Bj`.
- Output (text/json): ordered steps, each with branches and the reason it is safe; blocked
  branches with their findings. Exit 0 if everything is placed, 1 if something is blocked.

## 4. Scaling

- `BranchSummary` per branch against `merge-base(branch, T)`: O(n) summaries, cached on disk.
- **Interaction index:** `module → branches that change its API` and
  `module → branches that add references into it`. Pairs and culprit candidates come from
  joining these indexes, so unrelated branches cost nothing. Target: 50 branches with typical
  overlap in < 10 s warm cache.

## 5. Output contract changes

- Pairwise mode keeps JSON `version: 1` byte-for-byte.
- N-way modes emit `version: 2`: top-level `mode` (`"combined"` | `"plan"`), `target`,
  `integrated` (list of branches), `skipped`; findings gain `culprits: [..]` (sorted) and
  `resolved_by: [..] | null`. `plan` adds `steps: [{"branches": [..], "together": bool}]` and
  `blocked: [{"branch": .., "findings": [..]}]`.

## Open questions for reviewers

1. Is `commit-tree` chaining acceptable, or should we pass trees with `--merge-base` (Git ≥ 2.40)?
2. ddmin vs exhaustive subsets for culprit sets of size ≤ 3 — which is simpler to make deterministic?
3. Should `plan` evaluate pairwise rules on every step, or only CW005/CW006 on the integrated state?
4. Fixture strategy for 3–5-branch scenarios (conjunctive removal, fix-by-third-branch, stacked).

## Decisions after review (Terra: `nway-review-terra.md`, Sol: `nway-review-sol.md`)

- **D1 Virtual commits.** `commit-tree` chaining (real merge ancestry, Git 2.38). Fixed metadata:
  author/committer `crosswire <crosswire@invalid>`, date `@0 +0000`, message `crosswire virtual merge\n`,
  parents `(C(i-1), Bi)`; run with `-c commit.gpgSign=false` and an environment that ignores user
  identity/config. No refs are written. Cache key = (tool version, integration policy version, T, ordered S).
- **D2 Culprit sets.** Exhaustive enumeration of candidate subsets by size, then by sorted labels,
  for up to 6 candidates and subset size ≤ 3 → minimum cardinality, deterministic. The branch that
  owns the reference is always kept integrated. Larger cases → report the full candidate set with
  `culprits_exact: false`. Trials that hit a textual conflict are treated as "not reproducing".
- **D3 Resolution is tri-state** (`valid` / `broken` / `unknown`). Re-export chains are followed up
  to depth 5 with cycle detection; guarded definitions count as defined; `unknown` is never reported.
- **D4 State checks, not pairwise vetoes.** In `--combined` and `plan`, a state is judged only by
  rules evaluated **on the state**: CW005 (textual), CW006 (every added reference of every
  integrated branch, plus target references into changed modules — this subsumes CW001/CW002),
  CW003 (different definitions of one name added by two integrated branches) and CW004 (Django
  number collision / Alembic multiple heads in the state). Pairwise CW001/CW002 findings are
  reported for information but never block.
- **D5 "New" errors.** A finding is keyed by `(rule, path, symbol or path)` ignoring lines. Errors
  already present at `T` are never counted; a step is clean iff `findings(state + step)` adds no
  key that is absent from `findings(state)`.
- **D6 Atomic groups.** A `together` step is evaluated only on the state after the whole group;
  its intermediate states are not checked, and the output says it must land atomically
  (one merge-queue batch / octopus merge). A textual conflict inside the group invalidates it.
- **D7 Locations.** CW006 locations are re-extracted from the integrated state's files (the code
  that will actually exist after the merge); JSON marks them with `"location": "integrated"`.
- **D8 Stacks.** If `Bi` is an ancestor of `Bj`, `Bi` is ordered first. A branch fully contained
  in another one is still placed, gets `contained_in: [..]`, and changes it shares with its
  container are attributed only to the earliest branch that introduces them (no duplicates).
- **Fixtures:** Sol's plan (named-DAG RepoBuilder, oracle tables over ordered subsets, the 3/4/5-
  branch scenarios listed in `nway-review-sol.md`) is adopted as the v0.3 acceptance suite.
