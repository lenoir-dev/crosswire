# crosswire v0.3a — frozen plan (combined N-way check)

Status: APPROVED. Implements `docs/design/nway.md` decisions D1–D3, D5, D7 for
`check --combined`. `plan`, target-reference re-check (D4 part 2), state-level CW003/CW004 and
stacks (D8) are **v0.3b — out of scope here**. Ownership and git rules unchanged (Terra: `src/**`,
`README.md`; Sol: `tests/**`; nobody commits).

## CLI

`crosswire check --target T --combined [--src ..] [--format ..] [--no-cache] B1 .. Bn`

- `--combined` requires `--target` (else exit 2) and is incompatible with `--no-textual`.
- Without `--combined` every existing behaviour and output is unchanged.

## 1. `integrate.py`

```python
@dataclass(frozen=True, slots=True)
class Integration:
    commit: str                          # virtual commit of the final state (T itself if nothing merged)
    integrated: tuple[str, ...]          # labels, in merge order
    skipped: tuple[tuple[str, tuple[str, ...]], ...]   # (label, conflicted paths)

def integrate(repo, target_sha, branches: Sequence[tuple[str, str]]) -> Integration
```

D1 exactly: chain `merge-tree --write-tree` + `commit-tree` with fixed identity/date/message,
`-c commit.gpgSign=false`, env with `GIT_AUTHOR_*`/`GIT_COMMITTER_*` set, no refs written.
In-process memo keyed by `(prev_commit, branch_sha)`. A branch that conflicts with the current
state is skipped and integration continues with the next one.

## 2. `state.py` — symbol resolution in any commit

```python
Status = Literal["valid", "broken", "unknown"]
@dataclass(frozen=True, slots=True)
class Resolution:
    status: Status
    symbol: Symbol | None                # set when valid and a def/class with known params
    files: tuple[str, ...]               # repo files consulted (module file + re-export chain)

class StateIndex:
    def __init__(self, repo, commit, roots): ...
    def resolve(self, module: str, name: str) -> Resolution
```

- Module file = `<root>/<m as path>.py` or `<root>/<m as path>/__init__.py` (first root that has it).
- Module file missing → `broken` if `module` is an in-repo module of the caller's tip (see §3),
  otherwise `unknown`.
- Name defined (A1 rules: defs, classes, assignments, guarded definitions) → `valid`.
- Name bound by `from X import n [as name]` → resolve `X.n` recursively (depth ≤ 5, cycle →
  `unknown`); `import X as name` → `valid`. Bound by `*`-import or nothing → `broken`.
- Parse error in any consulted file → `unknown`.

## 3. Rule CW006 combined-break (error) and combined CW001/CW002

For every integrated branch `X` and every **added reference** `r` of `X` (its `BranchSummary`):

1. `tip = StateIndex(X.tip).resolve(r.module, r.name)`; continue only if `tip.status == "valid"`
   (third-party and already-broken references are never blamed on the merge).
2. `final = StateIndex(I.commit).resolve(...)`. Broken if `final.status == "broken"`, or `r.call`
   is set, not splatted, binds to `tip.symbol.params` and fails to bind to `final.symbol.params`
   (both known; reuse CW002's binder).
3. Culprits (D2): candidates = integrated branches ≠ X that changed any file in
   `tip.files ∪ final.files` against their own base, in merge order. Enumerate subsets by size
   1..3, then by sorted labels, over ≤ 6 candidates; the first subset S for which
   `integrate(T, [X] + S in merge order)` reproduces the break is the culprit set
   (`culprits_exact = true`). Otherwise culprits = all candidates, `culprits_exact = false`.
   Trials with a textual conflict do not reproduce.
4. `|culprits| == 1` → finding with rule `CW001` (missing name) or `CW002` (call binding), else
   `CW006`. Message for CW006: `` `m.f` is broken after merging {A, B}: <reason>; no single branch causes it ``.
5. Location (D7): the matching occurrence of `(module, name, call)` re-extracted from the same
   path in `I`; if the path is absent in `I`, the branch-tip location with `location = "branch"`.

Pairwise CW001/CW002 findings are **not** emitted in combined mode — the state check above
replaces them. Pairwise findings that would have fired but are fine in `I` are emitted as
`warning` with `resolved_by` = the minimal subset (same enumeration) of the other integrated
branches that makes the reference valid when integrated with X and the cause. CW003/CW004 stay
pairwise (informational, unchanged severities) among integrated branches. Each skipped branch
yields one CW005 per conflicted path with `branch` = the skipped branch and `culprits` = the
integrated labels at that point.

## 4. Output (JSON `version: 2`, only in combined mode)

```json
{"version": 2, "tool": "crosswire", "mode": "combined", "target": "<sha>",
 "integrated": ["a", "b"], "skipped": [{"branch": "c", "paths": ["x.py"]}],
 "findings": [{"rule": "CW006", "severity": "error", "message": "...", "branch": "c",
   "culprits": ["a", "b"], "culprits_exact": true, "resolved_by": null,
   "path": "app/use.py", "line": 3, "location": "integrated", "symbol": "m.f"}],
 "summary": {"errors": 1, "warnings": 0}}
```

Text: `path:line: ERROR CW006 [c × {a, b}] message`. SARIF/github: as v0.2 with culprits joined in
`properties`. Sorting/dedup as v0.1 with `culprits` added to the key.

## 5. Acceptance (Sol's scenarios, oracle-based)

1. **Conjunctive:** `m.f` = `def f` + guarded `try: from fast import f`; A deletes the def, B
   deletes the try-import, C adds a call → CW006 on C, culprits `[A, B]`, exact; every proper
   subset of {A, B, C} is clean; pairwise mode reports nothing.
2. **Fixed by third:** A removes `m.f`, B adds re-export `m.f`, C calls it → combined: no error,
   one warning `resolved_by: [B]`; pairwise mode: CW001 error (unchanged).
3. **Single culprit:** classic rename → combined reports CW001 with culprits `[A]`.
4. **Signature:** A adds a required param, C adds an old-arity call → CW002 culprits `[A]`.
5. **Decoy + competing fixes** (4 branches) → deterministic minimal culprits / resolved_by.
6. **Textual skip:** a conflicting branch is skipped, never enters `I`, gets CW005.
7. **Pre-existing break** at a branch tip and third-party imports → no findings.
8. Permuting branch order keeps the finding set (except `integrated` order / skipped choice when
   order genuinely changes which branch conflicts); refs (`git for-each-ref`), HEAD, index and
   worktree unchanged; Python 3.11 and 3.14 green.
