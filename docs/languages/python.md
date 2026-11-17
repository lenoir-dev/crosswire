# Python — supported conflict types (contract for recall measurement)

Status: FROZEN for the v0.4 pilot (architect). Recall in `docs/QUALITY.md` is measured only over the
types marked **supported**. Changing this list after the first evaluation requires a new
evaluation round; it may not be edited to improve numbers.

Analysis: stdlib `ast`, no runtime dependency. Source roots: `--src`, default `src` + repo root.

## Supported

| Id | Conflict type | Rules | Oracle evidence (pyright basic) |
| --- | --- | --- | --- |
| PY-1 | A module-level function, class or assignment is removed/renamed on one side; another side adds `from m import name` or `m.name` use | CW001, CW006 | `reportAttributeAccessIssue` / unknown import symbol |
| PY-2 | A module file is deleted or moved; another side adds an import of it | CW001, CW006 | `reportMissingImports` (first-party module) |
| PY-3 | A re-export chain (`from .x import f` in `m`) is broken by the combination of branches (depth ≤ 5) | CW001, CW006 | unknown import symbol |
| PY-4 | Signature change of an undecorated module-level function or a simple class `__init__` (required param added, param removed/renamed, keyword-only change, positional-only change, arity) vs. a new non-splatted call | CW002, CW006 | `reportCallIssue` (missing/unknown argument, too many positional) |
| PY-5 | Conjunctive removal: a name with several guarded definitions loses all of them only when ≥ 2 branches combine | CW006 | as PY-1 |
| PY-6 | Django migrations with the same number in the same app; Alembic revisions sharing a `down_revision` | CW004 | not a type-checker error → measured by replaying `makemigrations --check` / `alembic heads` where the project allows, otherwise reported separately as unmeasured |

Duplicate definitions (CW003) are warnings and excluded from precision/recall; they are reported
as a separate count.

## Explicitly unsupported (reported as coverage gaps, never as conflicts)

Instance and class method calls (`obj.m()`, `Cls.m()` other than via a module attribute), decorated
functions and classes with decorators that may change signatures, `*args`/`**kwargs` splats at the
call site, star-imports, `importlib`/`__import__`/`getattr`, conditional imports whose condition
we cannot see across branches (treated as defining), stub files (`.pyi`), namespace packages
outside the configured roots, third-party packages, type-only imports under `TYPE_CHECKING`
(treated as defining), runtime monkey-patching.

## Known precision risks to watch in the pilot

Re-exports via `__all__` manipulation, modules shadowed by packages of the same name, `src`-layout
detection in repositories with several packages, generated code checked into the repo.
