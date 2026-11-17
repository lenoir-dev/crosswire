# crosswire — frozen implementation plan (v1)

Status: ACCEPTED (T1–T4 done, 187 tests green). APPROVED by the architect after round-1 review by Terra (implementability) and Sol
(testability). This document overrides `PROPOSAL.md` wherever they differ. Contract changes go
through the architect; do not change them unilaterally.

Guiding principle: **conservative**. When resolution is uncertain, skip silently rather than
report. A false positive is worse than a false negative.

## 0. Tooling

- Python ≥ 3.11, runtime dependencies: none (stdlib only). Git ≥ 2.38 (needs `merge-tree --write-tree`).
- `pyproject.toml` (hatchling build backend), package in `src/crosswire`, console script
  `crosswire = crosswire.cli:main`, dev dependency group `dev = ["pytest>=8"]`.
- Commands: `uv sync`, `uv run pytest -q`, `uv run crosswire --help`, `uv run python -m crosswire`.
- crosswire is strictly read-only towards the repo: it never changes HEAD, index, worktree or refs.
  (`merge-tree --write-tree` writes loose objects only, which is acceptable.)

## 1. CLI

```
crosswire check [--repo PATH] [--base REF] [--src DIR]... [--format text|json|github]
                [--no-textual] BRANCH BRANCH [BRANCH...]
crosswire --version
```

- `--repo` default `.`; may be any directory inside a work tree.
- At least 2 distinct branches (after resolving to SHAs, duplicates are an error → exit 2).
- Pair base: `git merge-base A B` by default. With `--base REF`: base = resolved REF, which must be
  an ancestor of both A and B (`git merge-base --is-ancestor`), else exit 2 with a message.
  If A and B have no merge-base → exit 2.
- `--src DIR` (repeatable) sets the source roots. Default roots: `["src", "."]` if `src/` exists
  at the pair base, otherwise `["."]`.
- `--no-textual` disables CW005.
- Exit codes: `0` = no findings with severity `error` (warnings allowed); `1` = at least one
  `error` finding; `2` = usage error, invalid ref, git failure, git too old. Errors for code 2 go to
  stderr as `crosswire: error: <message>`; stdout stays empty in that case.
- Python files that fail to parse (`SyntaxError`) at some revision are skipped for that revision
  and reported once on stderr as `crosswire: warning: cannot parse <path>@<short-sha>`; this does
  not change the exit code.

## 2. Git layer (`git.py`)

All calls via `subprocess.run([...], cwd=repo, capture_output=True)` with env
`GIT_OPTIONAL_LOCKS=0`, `LC_ALL=C`, never through a shell. Non-zero exit (except documented ones) →
raise `GitError(message)` → CLI exit 2.

- `repo_root(path) -> Path` (`rev-parse --show-toplevel`)
- `git_version(repo) -> tuple[int, int, int]`; < 2.38 → `GitError`.
- `resolve(repo, ref) -> str` full SHA (`rev-parse --verify --end-of-options REF^{commit}`).
- `merge_base(repo, a, b) -> str | None`; `is_ancestor(repo, anc, desc) -> bool`.
- `changed_files(repo, base, tip) -> list[FileChange]` using
  `diff --name-status -z -M BASE TIP` (renames enabled), parsed from NUL-delimited output. `FileChange(status: Literal["A","M","D","R"], path: str, old_path: str | None)`;
  `C`/`T` statuses are mapped to `A`/`M`.
- `read_file(repo, rev, path) -> str | None` (`cat-file blob REV:PATH`; missing → `None`;
  decoded UTF-8 with `errors="replace"`). Cached per `(rev, path)`.
- `list_files(repo, rev, prefix="") -> list[str]` (`ls-tree -r -z --name-only`).
- `merge_tree_conflicts(repo, a, b) -> list[str]` (`merge-tree --write-tree --name-only -z
  --no-messages A B`): exit 0 → `[]`; exit 1 → sorted unique conflicted paths; other → `GitError`.

## 3. Model (`model.py`) — frozen dataclasses, `slots=True`

```python
ParamKind = Literal["posonly", "pos", "vararg", "kwonly", "varkw"]
Param(name: str, kind: ParamKind, has_default: bool)

SymbolKind = Literal["function", "class", "method", "variable"]
Symbol(module: str, qualname: str, kind: SymbolKind, path: str, line: int,
       params: tuple[Param, ...] | None,   # None = signature unknown / not checkable
       shape: str)                          # for rename hints: kind + param names/kinds

Reference(path: str, line: int, module: str, name: str,   # target module + top-level name
          call: CallShape | None)
CallShape(positional: int, keywords: tuple[str, ...], has_star: bool, has_starstar: bool)

ApiChange(kind: Literal["removed", "signature_changed"], module: str, qualname: str,
          old: Symbol, new: Symbol | None, rename_hint: str | None)

Severity = Literal["error", "warning"]
Finding(rule: str, severity: Severity, message: str, branch: str, other_branch: str,
        path: str, line: int, symbol: str | None)
#   branch = the branch whose *added* code is broken / where the location is
#   other_branch = the branch that caused it

Report(base_by_pair: dict[tuple[str, str], str], findings: list[Finding])
```

## 4. Python analysis (`python_analyzer.py`)

- `module_name_for_path(path, roots) -> str | None`: first root (in given order) that is a path
  prefix; strip `.py`; `pkg/__init__.py` → `pkg`; `.` root means repo root. Non-`.py` or not under
  any root → `None`. Path components that are not identifiers → `None`.
- `extract_symbols(source, module, path) -> dict[str, Symbol]`, keyed by qualname:
  - module-level `def`/`async def` → `function`; `class` → `class`; methods directly in a
    top-level class → `method` (`Class.meth`); module-level `Name = ...` / annotated assignments →
    `variable` (params `None`).
  - `params` is set **only** for undecorated module-level functions, and for undecorated classes
    without base classes other than `object` that define `__init__` directly (params of
    `__init__` minus the first parameter). Everything else → `None`.
  - If a name is defined more than once at module level, the last definition wins (Python
    semantics); `line` points to the last one.
- `extract_references(source, module, path, is_package) -> list[Reference]`:
  - Bindings from **module-level** imports only (imports inside functions/classes also count, but
    are resolved in the scope where they appear; a simple implementation may treat all imports as
    file-wide — **decision: file-wide is acceptable for v1**).
  - `from m import f [as g]` → reference `(m, f)` at the import line; later `g(...)` → reference
    `(m, f, call=shape)` at the call line.
  - `import m.sub [as x]`; `x.f(...)` / `x.f` → reference `(m.sub, f[, call])`. Only one attribute
    level after the bound module (no `x.Cls.meth`).
  - Relative imports are resolved with `module` + `is_package`; unresolvable (beyond top) → skip.
  - `from m import *`, `importlib`, `getattr` → ignored.
  - Names that are rebound locally (assigned / used as a function parameter / def'd in the file)
    shadow imports: if a bound import name is reassigned anywhere in the file → stop treating it
    as a reference (conservative).
- Analysis is cached by `(blob content hash, module, roots)`.

## 5. Diffing (`diffing.py`)

- `api_changes(base: dict[str, Symbol], tip: dict[str, Symbol]) -> list[ApiChange]`:
  - `removed`: qualname in base, not in tip.
  - `signature_changed`: in both, both `params` not `None`, and params differ.
  - Module removed / renamed (`D` / `R` FileChange) → all its symbols `removed` at the old module.
  - `rename_hint`: for a removed symbol, if exactly one symbol was *added* in the same module with
    the same `kind` and same `shape`, hint = its qualname. Ties/none → `None`. A hint never
    suppresses a finding.
- `added_references(base_refs, tip_refs) -> list[Reference]`: multiset difference keyed by
  `(path, module, name, call)` ignoring `line`; the survivors keep their tip line numbers;
  for `k` surplus occurrences, report the last `k` by line.
- A branch's added definitions: qualnames present in tip and absent at base, per module.

## 6. Rules (`rules/`) — each module: `RULE_ID`, `SEVERITY`, `check(ctx) -> list[Finding]`

`ctx` (`PairContext`) gives, for each side X of pair (A, B): its changed files, api changes per
module, added references, added definitions, plus helpers to read files/symbols at base and tip.
Every rule runs in both directions (X breaks Y, Y breaks X).

- **CW001 stale-reference (error)**: Y adds a reference `(m, n)` and X has `ApiChange(removed)`
  for top-level `n` in `m`, **and** Y's tip does not itself (re)define `m.n`. Message:
  `` `m.n` is used here but was removed in <X> `` + `` (renamed to `m.<hint>`?) `` if hinted.
- **CW002 call-signature (error)**: Y adds a reference with `call` to `(m, n)`; X has
  `signature_changed` for `m.n` with known new params; the call is not splatted; binding the call
  shape to X's new params fails per Python rules (too many positional, unknown keyword without
  `**kw`, missing required, keyword given for posonly param, duplicate value). It must also bind
  successfully to the base params (otherwise it was broken anyway → skip). Message names the
  concrete reason.
- **CW003 duplicate-definition (warning)**: X and Y both add the same qualname to the same module
  (top-level or method of same class) and the two definitions are not byte-identical
  (compare `ast.dump` of the nodes). Reported once per pair (location in Y, other_branch X; pick
  A as `other_branch` for determinism, i.e. location in the lexicographically-greater branch).
- **CW004 migration-collision (error)**:
  - Django: both add files `<dir>/migrations/NNNN_<name>.py` (NNNN = 4 digits) with the same `dir`
    and same number but different filenames; also when one side adds number N and the other side
    adds a different file with the same N. Reported once per collision.
  - Alembic: files under a dir containing `versions/` that define module-level
    `down_revision = "<str>"` or a tuple/list of str literals. Collision if both sides add
    revisions whose `down_revision` sets intersect on a non-empty string id. `None`/non-literal →
    ignored.
- **CW005 textual-conflict (error)**: one finding per conflicted path from `merge_tree_conflicts`,
  `line = 1`, `symbol = None`, reported once per pair with branch = B, other = A.

## 7. Engine (`engine.py`)

`analyze(repo, branches: list[str], base: str | None = None, src: list[str] | None = None,
textual: bool = True) -> Report`

- Pairs = all unordered pairs in the given branch order (`itertools.combinations`); document
  O(n²). Branch labels in findings are the names as given by the user.
- Modules a side did not touch are taken from the base, so references into untouched modules are
  still checked.
- Findings are deduplicated (same rule, branch, other_branch, path, line, symbol) and sorted by
  `(path, line, rule, branch, other_branch, symbol or "", message)`.

## 8. Output (`report.py`)

- **text**: `path:line: SEVERITY CWxxx [branch × other_branch] message`, then a summary line
  `N error(s), M warning(s) across K pair(s)`; `No semantic conflicts found across K pair(s).`
  when empty.
- **json** (exactly this shape, keys sorted, `indent=2`, nothing else on stdout):

```json
{
  "version": 1,
  "tool": "crosswire",
  "pairs": [{"a": "feat-a", "b": "feat-b", "base": "<sha>"}],
  "findings": [{"rule": "CW001", "severity": "error", "message": "...", "branch": "feat-b",
                "other_branch": "feat-a", "path": "app/x.py", "line": 3, "symbol": "billing.charge"}],
  "summary": {"errors": 1, "warnings": 0}
}
```

- **github**: `::error file=<path>,line=<line>,title=<rule>::<message>` (`::warning` for warnings),
  with property values escaping `%`→`%25`, `\r`→`%0D`, `\n`→`%0A`, `:`→`%3A`, `,`→`%2C`, and the
  message escaping `%`, `\r`, `\n`.

## 9. Ownership and workflow

| Task | Owner | Files | Depends on |
| --- | --- | --- | --- |
| T1 implementation | Terra | `pyproject.toml`, `src/crosswire/**`, `README.md`, `uv.lock` | PLAN |
| T2 test suite | Sol | `tests/**` only | PLAN (writes against contracts; runs once T1 lands) |
| T3 verification | Sol | `tests/**`, report to architect | T1 + T2 |
| T4 acceptance | Opus | `docs/**` | T3 |

- Nobody edits files owned by another agent. Bugs found by Sol are reported to the architect with
  a failing test name and the expected behaviour per this PLAN; the architect routes fixes to Terra.
- Nobody runs `git commit`, `git checkout`, `git stash`, `git reset` in the shared worktree.
  Tests build their own temp repos (`tmp_path`) and never touch this repository's git state.
- Test fixtures (`tests/helpers.py`, `RepoBuilder`): `git init -b main` in `tmp_path`, isolated
  config (`GIT_CONFIG_GLOBAL=/dev/null`, `GIT_CONFIG_NOSYSTEM=1`), fixed author/committer name,
  email and dates, `core.hooksPath` to an empty dir; helpers `write`, `delete`, `rename`, `commit`,
  `branch`, `checkout`. Every integration test asserts HEAD/index/worktree unchanged after analysis.

## 10. Acceptance criteria

1. `uv run pytest -q` passes; ≥ 1 positive and ≥ 1 negative test per rule; CLI exit codes 0/1/2
   covered; JSON shape test; github escaping test.
2. Demo scenario in `README.md` reproduces: base with `billing.charge(amount, currency)`; branch
   `rename-charge` renames it to `create_charge`; branch `add-refunds` adds a new call to
   `billing.charge` → `git merge-tree` is clean but `crosswire check rename-charge add-refunds`
   exits 1 with CW001 and the rename hint.
3. Running on a repo with no conflicting branches exits 0 and prints the "No semantic conflicts" line.

## 11. Amendment A1 (architect, after T1/T2)

1. **Re-exports are definitions.** `extract_symbols` also records names bound by module-level
   `from X import n [as m]` and `import X [as m]` as kind `variable` (params `None`). Turning
   `def charge` into `from .core import charge` is therefore *not* a removal (no CW001).
   `from X import *` binds nothing.
2. **Guarded definitions.** Definitions/assignments/imports nested in module-level `if`, `else`,
   `try`/`except`/`else`/`finally` and `with` blocks count as module-level (any branch defines
   the name; params `None` if the name is defined in more than one place).
3. **git:** `merge_tree_conflicts` must raise `GitError` when git reports a failure, even if the
   exit code is 1 (e.g. an invalid ref: exit 1 but stdout has no tree OID). Validate that the first
   NUL-separated field is a 40/64-hex OID; otherwise → `GitError`.
