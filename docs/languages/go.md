# Go — supported conflict types (contract for recall measurement)

Status: **FROZEN for 0.5b** (Polaris, 2026-11-18, after the S19a census). Incorporates PLAN-v0.5 Amendments P1
and P2. Recall is measured only over the types marked supported. Changing this list after the first Go
measurement requires a new evaluation round; it may not be edited to improve numbers.

Analysis: tree-sitter-go (pinned runtime and grammar, extra `crosswire[go]`), no type checker at runtime.

## Why this rule set (decision D-Go1)

S19a ([census](../validation/s19a-go-census.md)) replayed 334 merges of five public Go repositories and found
**zero** natural "green parents, clean merge, failing build" cases: 55 % of the merges were unlabellable
(pre-module history) and most of the rest had one parent ancestral to the other. The census therefore gives
no empirical ordering among the candidates, and zero observations do not show that the conflicts are rare.

The 0.5b set is chosen a priori: GO-1…GO-4 are the Go counterparts of the conflict types already supported and
measured for Python (PY-1, PY-2, PY-4, CW003), each has a single unambiguous compiler category, and each can be
proven syntactically. GO-6…GO-9 stay candidates for 0.6, GO-5 stays deferred until a build-context matrix
exists. Natural Go positives are searched for by S19 with a preregistered selection over module-era histories
with divergent parents; control cases and synthetic smoke cases are never promoted to natural positives.

## Model

- One unambiguous module per analysis root: the module path comes from `go.mod` (which may sit below the
  repository root); a nested `go.mod` ends the module. A change to `go.mod` invalidates package identities, so
  proofs that depend on them become gaps.
- A package is a directory; its import path is the module path plus the relative directory. The package
  **name** comes from the package clause, not the directory name. Import bindings come from the imported
  package clause and explicit aliases, with lexical shadowing. `internal/` accessibility is checked.
- Exported means the identifier starts with a Unicode upper-case letter (category Lu). Only exported top-level
  identifiers can be referenced from other packages.
- All `.go` files of a directory form one package namespace. Per-file import names belong to their file.
- Production code only: `_test.go` files (definitions **and** uses) are excluded and reported as a gap;
  `vendor/` is excluded; first-party links affected by `replace` directives or `go.work` are gaps.
- Third-party and standard-library packages are `unknown`, not gaps.
- Files with build constraints (`//go:build`, `// +build`, `_GOOS`/`_GOARCH` file names, cgo) are not used in
  proofs: a proof that depends on such a file is a gap.
- tree-sitter `ERROR` or `MISSING` nodes inside a proof's span make that proof `unknown`.

## Supported

| Id | Conflict type | Rules | Oracle category (go/types code, matched by position) |
| --- | --- | --- | --- |
| GO-1 | An exported top-level func/type/var/const is removed or renamed on one side; another side adds a `pkg.Name` use | CW001, CW006 | undeclared / missing qualified name |
| GO-2 | A first-party package directory is removed or moved; another side imports its path | CW001, CW006 | package-loading failure for a first-party import path |
| GO-3 | A top-level function's signature changes so that it can no longer accept the `n` arguments of a new call `pkg.F(…)` / `F(…)`. Grouped and unnamed parameters are counted, variadic functions have a minimum arity, explicit `...` calls are handled; adding a trailing variadic parameter does **not** break. Calls with a multi-value argument, conversions, callable variables, method calls and generic calls are `unknown` | CW002, CW006 | wrong argument count |
| GO-4 | Two branches add the same identifier to one package namespace: funcs, types, vars, consts, methods `T.M`, and per-file import names; in any files, **including the same file**; identical declarations included. `_` and `init` are exempt; constraint-dependent pairs are `unknown`. Identity is the declaration pair; every location is kept | CW003 (**error** for Go), CW006 | duplicate declaration |

## Candidates (not supported in 0.5b)

GO-5 conjunctive removal across build-tag variants (deferred until a declared build-context matrix exists);
GO-6 result-count change vs a syntactic multi-assignment; GO-7 per-file imports after a clean merge (unused or
missing; a duplicate import name is GO-4); GO-8 import cycles; GO-9 same-package unqualified references. All were verified against the
compiler by Vega; the S19a apparatus classifies them, so S19 counts them as observations without scoring them.

## Unsupported (coverage gaps, never conflicts)

Parameter or result **type** changes (no type inference), method calls on values (`x.M()`), interface
satisfaction, struct field changes, generic instantiation, embedding and promotion, cgo, `//go:linkname`,
dot-imports (`import . "p"`), generated code with build tags we cannot evaluate, vendored modules, test code.

## Oracle

Pinned Go toolchain (S19a: Go 1.27.1): `GOFLAGS=-mod=readonly go build -gcflags=-e ./...` with
`GOTOOLCHAIN=local`, `GOENV=off`, `GOWORK=off`, `CGO_ENABLED=0`, fixed GOOS/GOARCH, no custom tags, fixed isolated
GOCACHE/GOMODCACHE, dependencies prefetched and hashed, labelling with `GOPROXY=off`, `GOSUMDB=off`,
`GOVCS=*:off`. It is the semantic oracle. Diagnostics are matched by position and pinned go/types error code,
never by message text. `go vet ./...` is a separately captured channel, split by category, and never decides a
label. A case has one root cause; dependent-package masking is stated in the report, and ambiguous multi-error
cases are excluded.
