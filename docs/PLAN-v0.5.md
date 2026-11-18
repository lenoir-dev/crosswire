# crosswire v0.5 — plan: one core, many languages (Python behind an adapter, then Go)

Status: DRAFT (Polaris, 2026-11-18) for review by Altair, Deneb and Vega; becomes binding with their
amendments. Inputs: `docs/design/v0.5-inputs.md`, `docs/VISION-v1.md` (V3, V5, V10), PLAN-v0.4 acceptance
decisions. Two releases, so a refactor can never hide behind a feature:

| Release | User value | Gate |
| --- | --- | --- |
| **0.5a** | Same results, faster many-branch pairwise mode, trial telemetry; **first holdout measurement** for Python | Python outputs byte-identical to 0.4.0 before any additive change; holdout report |
| **0.5b** | `pip install crosswire[go]`: the same guarantees for Go repositories, polyglot repos | Go conformance + Go development corpus + polyglot test |

## 1. Architecture (0.5a)

```
core:      git · integrate · engine (BranchSummary) · culprits · planner · coverage · reports · cache
adapters:  crosswire/lang/python (stdlib ast)      crosswire/lang/go (tree-sitter, extra)
```

```python
class LanguageAdapter(Protocol):
    name: str                                    # "python", "go"; part of every symbol identity
    version: str                                 # enters the cache key
    def claims(self, path: str) -> bool
    def context(self, snap: Snapshot) -> object  # roots / go.mod module path …, cached per commit
    def module_of(self, path: str, ctx) -> str | None
    def symbols(self, src: Source, ctx) -> SymbolTable           # identity = (language, module, qualname)
    def uses(self, src: Source, ctx) -> list[Use]                 # site span + target + opaque call shape
    def resolve(self, snap: Snapshot, module: str, name: str, ctx) -> Verdict
    def api_changes(self, old: SymbolTable, new: SymbolTable) -> list[ApiChange]
    def check_call(self, use: Use, old: Symbol, new: Symbol) -> Verdict
    def gaps(self, src: Source, ctx) -> list[Gap]                 # unsupported constructs in scope
    def rules(self) -> list[Rule]                                 # language-specific rules (CW004 …)

Verdict = valid | broken(reason) | unknown(reason)   # adapters never raise for user code
```

- The core never imports `ast`; CW001/CW002/CW003/CW006 become language-neutral and ask the adapter.
- **One** call-compatibility implementation (`check_call`) for pairwise, combined and plan (removes the
  drift Altair reported).
- Registry: Python is always present; other adapters load if their extra is installed. A repository
  containing files of a language whose extra is missing reports `limitations["language-extra-missing:<lang>"]`
  with a file count and `coverage: partial` — never silent success.
- Identities are per language; references never cross languages; same module names in two languages
  are distinct (polyglot rule).
- Cache key gains adapter name + version; cache schema bump.

## 2. 0.5a tasks

| Task | Owner | Deliverable |
| --- | --- | --- |
| T21 adapter refactor | Altair | §1 for Python only. **Gate:** every golden, every v0.4 fixture and the 16 review scenarios byte-identical in all modes/formats; S14 within budgets |
| T22 pairwise batching | Altair | batch merge-base/merge-tree work for many pairs (30 branches: pairwise ≤ combined × 2 warm) |
| T23 trial telemetry | Altair | `limits.trials` (performed / limit) in combined and plan (additive; goldens refreshed after T21's gate) |
| T24 memory | Altair | peak RSS of the 30-branch plan reported by S14 and within the v0.4 budget |
| S16 conformance kit | Deneb | language-neutral scenario templates (rename, delete, move module, arity change, conjunctive 3-branch, fix-by-third, open module, star/dynamic) rendered by a per-language renderer; Python renderer first |
| S17 natural corpus | Deneb | development corpus with natural positives (mined history replays) and ≥ 5 eligible repositories; eligibility amendment M3 below |
| S18 first holdout measurement | Deneb | measure the sealed v2 holdout once against the frozen 0.5a source; report per QUALITY gates; Vega audits before publication |
| A-review | Vega | design review of this plan; code review of T21–T24; audit of S17/S18 |

**Amendment M3 (declared now, before any new number):** a development case is eligible when the oracle
reports **no new diagnostics relative to the target** (instead of a fully green target). Applies to the
development corpus only; the sealed v2 holdout keeps the policy it was sealed with.

## 3. 0.5b — Go (`docs/languages/go.md` is the contract)

| Task | Owner | Deliverable |
| --- | --- | --- |
| T25 Go adapter | Altair | tree-sitter-go (pinned runtime + grammar, extra `crosswire[go]`); go.mod module path, packages = directories, exported = capitalised, build-tag files as guarded definitions, `replace`/`go.work` targets → `unknown` |
| T26 Go rules | Altair | GO-1…GO-5 of the contract; CW003 is an **error** for Go (redeclaration fails to compile) |
| T27 polyglot | Altair | Python + Go in one repository: independent analysis, combined report, per-language coverage |
| S19 Go conformance + corpus | Deneb | S16 templates rendered for Go; Go development corpus (oracle `go build ./... && go vet ./...`, pinned Go), ≥ 5 repositories |
| S20 Go holdout | Deneb | sealed, not measured in 0.5b |

## 4. Acceptance

0.5a: T21 byte-identical gate proven by Deneb **and** Vega independently; full suites 3.11/3.14; S14 within
budgets; holdout report published with honest gates (pass, fail or insufficient — no tuning on holdout).
0.5b: Go conformance green, Go development metrics, polyglot test, install matrix (core-only and `[go]` on
3.11–3.14, Linux/macOS) in CI.

## Amendment P1 — decisions on Altair's and Deneb's reviews (`docs/design/v0.5-review-{altair,deneb}.md`)

Both reviews are accepted almost entirely. Binding changes:

**Protocol (replaces the sketch in §1 where they differ)**
- `resolve(snap, use, ctx) -> Resolution` is caller-aware and returns evidence: status, resolved binding or
  candidate set, reason, consulted files, context dependencies, gaps. Module existence and member resolution are
  separate operations; package imports are uses (incl. Go blank imports).
- `Snapshot` = immutable Git-tree access provided by the core (read, list); adapters never read the working tree,
  run language tools or follow paths outside the repository. `context` is recomputed for base, tips and every
  virtual state.
- Symbol tables hold **bindings** (one or more declarations with guards, spans, visibility and an opaque signature
  payload) keyed by language-qualified identity everywhere (summaries, indexes, prefilter, dedup).
- `check_call(use, old_bindings, new_bindings)` must prove the call valid on the old side before it may report
  breakage on the new side; `unknown` on either side suppresses the finding. Python reason texts are unchanged.
- **Package/module aggregation** precedes `api_changes` (moving a Go function between files is neither a removal
  nor an addition).
- Additional adapter hooks: definition comparison (CW003), integrated-state rules with explicit pairwise/state
  phases (Go redeclarations are re-checked on final and trial states), coverage sites, hints.
- Parse recovery (tree-sitter `has_error`/missing nodes) makes affected proofs `unknown`; adapter programming
  errors stay operational errors (exit 2), never silently become "malformed user code".

**T21 sequencing and gate**
- T21a (Deneb): immutable differential baseline from tag `v0.4.0` (object and source-file hashes): separate
  processes, identical fixtures, paths, locale, versions and arguments; raw stdout/stderr/exit compared for every
  mode × format, schema output, error paths, cold/warm/no-cache, pre-seeded and malformed caches, permutations and
  the scenarios listed in `tests/test_vega_v03.py` / `tests/test_vega_v04.py`. No projections, sorting or
  regenerated expectations. Vega replays it with her own comparator.
- T21b (Altair): extraction with delegation shims in small, independently green steps; shims are removed only
  after Deneb's and Vega's equality checks. T21c: adapter API + cache schema versioning, context fingerprints in
  disk and run caches. Telemetry, `language` fields and missing-extra reporting come **after** the checkpoint.
- T22/T23/T24 start only after the T21 checkpoint is accepted. T22 target: warm **p95**, 30 branches, pairwise ≤
  2 × combined, with a capability-checked fallback for Git 2.38. T23 counts actual integrations (cache hits listed
  separately), run-wide, with an enforced limit or `limit: null`. T24 adds a blocked, search-heavy 30-branch case;
  the v0.4 per-cell p95/RSS budgets stay binding.

**M3 (replaces the draft wording)**
`delta(state) = diagnostics(state) − mapped(baseline)` using pinned (rule, path, symbol, occurrence, root cause)
identities. Eligible: every tip has an empty delta. Positive: the integrated state has a new supported,
attributable delta absent from every tip; control: none. Ambiguous identities, incomplete coverage and
environment failures stay unlabelled. M3 has its own synthetic oracle tests, is frozen before any new label, is
reported as a separate development-only stratum, never relabels past exclusions and never touches v2.

**S18 holdout (first measurement, 0.5a)**
- Expected shape (aggregate only): 240 cases, 60 positives, 4 repositories. Per-rule cells have ≤ 20 positives,
  so even a perfect cell has a Wilson lower bound of ~83.9 %: **per-rule cells are reported, not gate-evaluated**.
  With 4 repositories the clustered interval is not estimable, so the micro result can be at most a
  **provisional** pass, never a v1.0 gate pass.
- Apparatus amendment H1 (the only one allowed): durable per-case private journaling, a no-rerun failure policy,
  release label `0.5a`, and correct complementary cell suppression. Labels are untouched; the amended apparatus is
  hashed, committed and audited by Vega **before** the attempt; S18 runs from an immutable archive of that commit.
  A rehearsal on synthetic private fixtures precedes the single real attempt.
- S17/M3 development happens outside the sealed apparatus files.

**Go (contract changes in `docs/languages/go.md`)**
- One unambiguous module (may be below the repo root; a nested `go.mod` ends it); `go.mod` edits invalidate package
  identities. Import bindings come from the imported package clause and explicit aliases, with lexical shadowing;
  `internal/` accessibility is checked; exports use Unicode category Lu.
- Production code only: `_test.go` definitions **and** uses are excluded (reported as a gap). `vendor/` excluded;
  `replace`/`go.work`-affected first-party links are gaps (not ordinary external unknowns).
- Build constraints (`//go:build`, `// +build`, `_GOOS/_GOARCH` file names, cgo) make proofs that depend on those
  files gaps in 0.5b. **GO-5 is cut.** GO-3/GO-4 are supported only for unconstrained files.
- GO-3: grouped and unnamed parameters, variadic minimum arity, explicit `...` calls; a call whose argument is a
  multi-value call is `unknown`; conversions, callable variables and generic calls are `unknown`.
- GO-4: reports identical declarations too (Python's equal-AST suppression does not apply), excludes `_` and
  `init`, keeps every declaration location; identity is a declaration pair.
- Oracle: pinned toolchain with `GOTOOLCHAIN=local`, `GOWORK=off`, fixed GOOS/GOARCH/CGO/tags, dependencies
  prefetched and hashed, labelling with `GOPROXY=off`; `go build ./...` is the semantic oracle, `go vet` a
  separately captured channel. Candidate repositories (dependency-light, to be verified green): google/uuid,
  spf13/pflag, julienschmidt/httprouter, go-chi/chi, rs/cors.

**Packaging and support matrix**
`[project.optional-dependencies] go = ["tree-sitter==<pin>", "tree-sitter-go==<pin>"]`, lazy-loaded; absent
extras and broken bindings are distinguished; ABI checked at load. Claimed platforms: Linux (x86_64, aarch64) and
macOS (arm64, x86_64), Python 3.11–3.14; Windows is not claimed yet. CI tests core-only and `[go]` installs with
binary-only resolution.
