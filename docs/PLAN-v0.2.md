# crosswire v0.2 — frozen plan (harden pairwise + N-way groundwork)

Status: APPROVED by the architect. `docs/PLAN.md` (v0.1 + A1) stays in force unless overridden here.
Ownership and git rules from PLAN.md §9 are unchanged: Terra → `src/**`, `pyproject.toml`,
`uv.lock`, `README.md`, `action.yml`; Sol → `tests/**`, `benchmarks/**`, `docs/validation/**`;
Opus → the rest of `docs/**`. Nobody commits; the architect commits accepted milestones.

## 12.1 BranchSummary (T4)

```python
@dataclass(frozen=True, slots=True)
class BranchSummary:
    label: str; tip: str; base: str; roots: tuple[str, ...]
    changes: tuple[FileChange, ...]
    api: dict[str, tuple[ApiChange, ...]]           # module -> changes
    references: tuple[Reference, ...]               # added references
    definitions: dict[str, dict[str, Symbol]]       # module -> added symbols
    redefined: frozenset[tuple[str, str]]
    migrations: dict[str, str]                      # added migration path -> source
    touched_modules: frozenset[str]                 # modules whose API changed
    referenced_modules: frozenset[str]              # target modules of added references

def summarize(repo, label, tip, base, roots) -> BranchSummary
```

- `engine.analyze` builds summaries once per `(tip, base, roots)` and rules consume
  `PairContext(a: BranchSummary, b: BranchSummary, ...)`. The behaviour and all v0.1 outputs stay
  byte-identical (Sol's S4 guard enforces this).
- Code style for all of `src/**`: one statement per line, no `;`, docstrings on public functions,
  no inline imports. Pure refactor first, features after.

## 12.2 `--target REF` and prefilter (T5)

- `--target REF` (mutually exclusive with `--base`, else exit 2): every branch is summarised once
  against `merge-base(branch, target)`. Pair base reported in JSON = `merge-base(a, b)` (unchanged
  field meaning); CW005 still uses `merge-tree a b`.
- Without `--target` behaviour is exactly v0.1.
- Prefilter (both modes): semantic rules for a pair run only if
  `a.touched_modules ∩ b.referenced_modules`, the reverse, or `a.definitions.keys() ∩ b.definitions.keys()`
  is non-empty, or both have migrations. CW005 always runs (unless `--no-textual`).

## 12.3 Cache (T6)

- Location `$(git rev-parse --git-common-dir)/crosswire/cache/v1/<sha256>.json`, key =
  `(crosswire.__version__, base, tip, roots)`. Atomic writes (temp file + `os.replace`); corrupt or
  unreadable entries are ignored and recomputed. `--no-cache` disables reads and writes.
- Results with and without cache are identical.

## 12.4 Outputs (T7)

- `--format sarif`: SARIF 2.1.0, one run, `tool.driver.name = "crosswire"`, rules CW001–CW005 with
  `shortDescription`, results with `ruleId`, `level` (`error`/`warning`), `message.text`,
  physical location (`artifactLocation.uri` = repo-relative path, `region.startLine`), and
  `properties: {branch, other_branch, symbol}`. Deterministic (sorted keys, same order as JSON).
- Unknown ref → `crosswire: error: unknown revision: <ref>` (exit 2).
- `action.yml` (composite): inputs `target` (default `main`), `branches` (default: all remote
  branches with an open PR, via `gh pr list --json headRefName`), `format` (default `github`);
  installs with `pip install .` from the action path and runs `crosswire check --target ...`.

## 12.5 Verification (Sol)

- S4: golden test — run all existing scenarios through `analyze` and the CLI, compare with
  snapshots recorded from the v0.1 commit `31acb87` (build them by running the old version from a
  `git worktree` in a temp dir, never in this worktree). Order invariance: permuting branch
  arguments changes only `pairs` ordering, never the finding set. Cache on/off identical.
- S5: pick a mid-size, actively developed pure-Python project with ≥ 15 open PRs (suggested:
  `pallets/flask`, `encode/httpx` or `pydantic/pydantic`), clone into `/tmp`, fetch
  `refs/pull/*/head`, run `crosswire check --target <default branch> --format json` on the open
  PR heads; triage every finding as TP / FP / unclear, with a one-line reason each. Write
  `docs/validation/v0.2.md` (repo, commit, PRs, timings, table of findings, FP root causes).
- S6: `benchmarks/bench_scale.py` generating a 30-branch synthetic repo; report cold/warm cache
  and prefilter timings.

## Acceptance

All tests green on Python 3.11 and 3.14; v0.1 snapshots identical; SARIF validates against the
schema shape test; field validation report delivered with FP rate; benchmark numbers recorded.

## Amendment A2 (architect decision after T4–T7 / S4–S6)

The "byte-identical to v0.1" and "order invariance" requirements contradicted each other for
CW005. **Order invariance wins**: CW005 findings are oriented canonically like CW003/CW004 —
`branch` = the lexicographically greater label, `other_branch` = the smaller one, message
`textual conflict with <other_branch>`. Golden snapshots are re-recorded for CW005 only; every
other v0.1 output must remain identical. Cache entries must round-trip to equal objects
(normalise JSON lists back to tuples/frozensets) so a warm cache really skips diffing.
