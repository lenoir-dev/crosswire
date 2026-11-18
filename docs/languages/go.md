# Go — supported conflict types (contract, DRAFT for v0.5b)

Status: DRAFT (Polaris), amended by PLAN-v0.5 Amendment P1 (binding where it differs). Frozen before the first Go measurement; recall is measured only over the types
marked supported. Analysis: tree-sitter-go (no type checker at runtime). Oracle: pinned
`go build ./... && go vet ./...`; vet findings unrelated to the change are classified separately.

## Model

- Module path from `go.mod`; a package is a directory; its import path = module path + relative dir.
- Exported = identifier starts with an upper-case letter. Only exported top-level identifiers can be
  referenced from other packages; unexported ones matter only inside the same package.
- A package spans several files: definitions from all `.go` files of the directory (excluding
  `_test.go` for non-test packages) form one namespace.
- Files with build constraints (`//go:build`, `// +build`, `_GOOS`/`_GOARCH` file names, cgo) are not analysed
  for GO-3/GO-4 proofs in 0.5b: dependent proofs become coverage gaps. (GO-5, conjunctive build-tag variants,
  was cut until a declared build-context matrix exists.)
- Production code only: `_test.go` files (definitions and uses) are excluded and reported as a gap;
  `vendor/` is excluded; `replace`/`go.work`-affected first-party links are gaps.
- Imports resolved through `replace` directives or `go.work` to paths outside the repository, and all
  third-party/stdlib packages, are `unknown` (not gaps).

## Supported

| Id | Conflict type | Rules | Oracle evidence |
| --- | --- | --- | --- |
| GO-1 | An exported top-level func/type/var/const is removed or renamed on one side; another side adds a `pkg.Name` use | CW001, CW006 | `undefined: pkg.Name` |
| GO-2 | A package directory is removed or moved; another side imports its path | CW001 | `package … is not in std` / no required module provides package |
| GO-3 | A function's parameter count changes (non-variadic arity, variadic added/removed; grouped and unnamed params counted) vs a new call `pkg.F(…)` with the old arity; calls with `...` or a multi-value argument, conversions, callable variables and generic calls are `unknown` | CW002, CW006 | `not enough / too many arguments in call` |
| GO-4 | Two branches add the same top-level identifier (also identical declarations; never `_` or `init`) to the same package in **different unconstrained files** — a textually clean merge that fails to compile; identity = declaration pair | CW003 (**error** in Go) | `X redeclared in this block` |

## Unsupported (coverage gaps, never conflicts)

Parameter or result **type** changes (no type inference), method calls on values (`x.M()`), interface
satisfaction, struct field changes, generics instantiation, embedding/promotion, cgo, `//go:linkname`,
dot-imports (`import . "p"`), generated code with build tags we cannot evaluate, vendored modules.
