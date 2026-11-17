# crosswire — semantic merge-conflict detector for parallel branches

Status: SUPERSEDED by PLAN.md (accepted)
Architect / acceptor: Opus 5.5 · Implementation: GPT-6.1 Terra · Tests & verification: GPT-6.1 Sol

## Problem

Teams increasingly run many coding agents (and humans) in parallel worktrees. Git happily merges
branches that touch different lines, but the result is often broken:

- branch A renames `billing.charge()` to `billing.create_charge()`; branch B adds a new call to
  `billing.charge()` → clean merge, `ImportError`/`AttributeError` at runtime;
- branch A adds a required parameter to `send_email(to, subject)`; branch B adds a call with the
  old arity → clean merge, `TypeError`;
- both branches add Django migration `0007_*.py` in the same app, or two Alembic revisions with
  the same `down_revision` → clean merge, "multiple heads" / conflicting migrations;
- both branches add a top-level `def parse_config` to the same module in different places → clean
  merge, the second definition silently shadows the first.

Merge queues catch some of this by building after the fact, which is slow and does not explain
*which pair of branches* collides or *why*. GitHub has no maintained, well-known standalone tool
that checks a set of branches **pairwise and before merging** (only one 0-star hackathon repo was
found).

## Product

`crosswire` — a zero-dependency Python CLI (stdlib only, Python ≥ 3.11) run locally or in CI:

```
crosswire check [--repo PATH] [--base REF] [--format text|json|github] BRANCH BRANCH [BRANCH...]
```

- For every unordered pair of branches (A, B) it computes the merge-base, the API changes each
  side made relative to that base, and the references each side *added*, then reports
  cross-branch collisions in both directions.
- `--base` (optional) overrides the merge-base (e.g. `main`).
- Exit codes: `0` no findings at severity error; `1` at least one error finding; `2` usage/git error.
- `--format json` emits a stable machine-readable report; `--format github` emits
  `::error file=...,line=...::` workflow annotations.

## Rules (MVP)

| id | severity | detects |
| --- | --- | --- |
| `CW001 stale-reference` | error | B adds an import/attribute reference/call to a symbol that A removed or renamed (rename suggested in the message) |
| `CW002 call-signature` | error | B adds a call that is incompatible with A's new signature: missing required arg, unknown keyword, too many positional args |
| `CW003 duplicate-definition` | warning | A and B both add a top-level (or same-class) definition with the same name to the same module |
| `CW004 migration-collision` | error | Django: both add `NNNN_*.py` with the same number in the same `migrations/` dir. Alembic: both add revisions with the same `down_revision` |
| `CW005 textual-conflict` | error | plain git conflicts, via `git merge-tree --write-tree` (reported for completeness) |

Python is the only analysed language in the MVP (stdlib `ast`), behind an analyzer interface so
TS/Go can be added later. Out of scope for the MVP: type inference, method calls on instances,
star-imports, dynamic `getattr`, non-Python languages.

## Architecture

```
src/crosswire/
  __init__.py          __version__
  __main__.py          python -m crosswire
  cli.py               argparse, output selection, exit codes
  git.py               thin subprocess wrapper over git (no GitPython)
  model.py             frozen dataclasses: Param, Symbol, Reference, ApiChange, Finding, Report
  python_analyzer.py   extract_symbols(), extract_references(), module_name_for_path()
  diffing.py           api_changes(base_symbols, tip_symbols) incl. rename heuristic
  rules/               one module per rule; each exposes RULE_ID and check(ctx) -> list[Finding]
  engine.py            analyze(repo, branches, base=None) -> Report (pairwise, both directions)
  report.py            text / json / github formatters
tests/                 pytest; real temp git repos built by a RepoBuilder helper
```

### Key contracts (to be frozen in PLAN.md after review)

- `git.py`: `merge_base(repo, a, b) -> str`, `changed_files(repo, base, tip) -> list[FileChange]`
  (`status` in A/M/D/R, `path`, `old_path`), `read_file(repo, rev, path) -> str | None`,
  `merge_tree_conflicts(repo, a, b) -> list[str]`, `resolve(repo, ref) -> sha`.
- `python_analyzer.extract_symbols(source, module) -> dict[str, Symbol]` keyed by qualname
  (`func`, `Class`, `Class.method`, module-level assigned names); `Symbol.params` describes
  positional-only / positional / keyword-only / *args / **kwargs and defaults.
- `python_analyzer.extract_references(source, module) -> list[Reference]` resolving
  `from m import f [as g]`, `import m [as x]; x.f(...)`, relative imports; for calls records
  positional count, keyword names, and whether `*args`/`**kwargs` were splatted (→ skip arity checks).
- "Added references" of a branch = references in its changed files at tip minus references in the
  same files at base, compared by `(file, target_module, name, call_shape)` ignoring line numbers.
- Symbols of a module that a branch does not touch are read at the merge-base, so B's new reference
  into an untouched module is still checked against A's changes.

## Process

1. Round 1 — Terra and Sol review this proposal and reply with concrete objections/additions.
2. Architect consolidates into `docs/PLAN.md` (frozen contracts, task split, acceptance criteria).
3. Build — Terra owns `pyproject.toml`, `src/**`, `README.md`; Sol owns `tests/**`. Sol's tests
   are written against PLAN.md contracts in parallel and then run against Terra's code; failures
   are routed through the architect.
4. Acceptance — architect independently runs the suite and an end-to-end scenario repo.
