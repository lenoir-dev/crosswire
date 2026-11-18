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
