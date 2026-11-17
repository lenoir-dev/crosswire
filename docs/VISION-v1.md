# crosswire v1.0 — vision, architect decisions and definition of done

Status: ADOPTED by the architect (Opus 5.5), 2026-11-17. Source: the owner's "Crosswire v1.0 —
Product Vision & Release Objectives". This document records what we take as-is, what the
architect changes (with reasons, as the vision permits), and the bar v1.0 must meet.

## 1. Mission (adopted unchanged)

Detect potentially incompatible changes on parallel Git branches **before** they are merged,
explain why, and recommend a safe integration strategy — for a developer with a few feature
branches and for an orchestrator running dozens of coding agents. Silence is never a proof of
correctness: crosswire reports the limits of what it checked.

## 2. Where we are (gap analysis at v0.3a, commit `ed3c095`)

| Vision area | State today | Gap to v1.0 |
| --- | --- | --- |
| A. N-branch analysis | `--combined` virtual integration, CW006 with exact minimal culprit sets (≤ 6 candidates, size ≤ 3), order-independent findings | merge plan, target references, explicit coverage reporting, alternative orders, tested at 5/10/30 branches |
| B. Languages | Python only (stdlib `ast`); Python semantics are wired into `engine`, `combined`, `state` and rules | language-adapter architecture + four more languages with documented depth |
| C. Planner | not started (v0.3b planned) | plan + explanations + alternatives + coverage |
| D. Diagnostics | rule, severity, branches, path, line, symbol, culprits, rename hint | remediation hint for every rule, explicit uncertainty/limits, versioned JSON Schema |
| UX / integration | CLI, JSON v1/v2, SARIF, GitHub Action, cache, read-only guarantee | quickstart, documented contracts, real examples, robustness against odd git states |
| Quality | 257 tests; field run on 20 httpx PRs: 7 TP / 0 FP, **all textual** | independent labelled corpus, semantic precision/recall per language and rule |
| Performance | 30 branches / 435 pairs ≈ 4.5 s warm (M5) | 5/10/30 branches × repo sizes, cold/warm, budgets, bounded combinatorics |

## 3. Architect decisions

- **V1 — Bar accepted.** ≥ 5 languages and solid work with ≥ 5 branches are non-negotiable for v1.0.
- **V2 — Language set: Python, TypeScript/JavaScript, Go, Java, PHP. C++ is replaced by
  TypeScript/JS** (the vision allows a justified swap):
  - C++ cannot be analysed conservatively without the build: overload resolution, templates,
    macros, header/include paths and ADL depend on `compile_commands.json` and effectively a
    compiler front-end. A syntax-level C++ analyser would either drown users in false positives or
    say almost nothing — both violate the precision-first principle.
  - TypeScript/JS has far higher demand in exactly our audience (web teams, agent-generated code),
    explicit `import`/`export` graphs that map well onto our model, and a cheap oracle (`tsc`).
  - C++ stays on the post-1.0 list as an adapter driven by `compile_commands.json` + libclang.
- **V3 — Dependencies.** The core and the Python adapter stay stdlib-only (`pip install
  crosswire` keeps working everywhere). Other languages are optional extras
  (`crosswire[go]`, `[ts]`, `[java]`, `[php]`, `[all]`) built on pinned **tree-sitter** grammars:
  one proven parser family, wheels for all major platforms, no compilers at runtime. Compilers
  and type checkers are used only by the evaluation harness as the oracle, never by crosswire itself.
- **V4 — Quality before breadth.** The measurement harness and the labelled corpus (v0.4) come
  *before* new languages. Adding four languages of unmeasured quality would produce a big number
  of features nobody can trust.
- **V5 — Language adapters, one core.** Every language implements the same `LanguageAdapter`
  contract (module mapping, symbol extraction with visibility, reference extraction, tri-state
  resolution in any commit, call compatibility). Rules CW001/CW002/CW003/CW006 become
  language-agnostic over that model; language-specific rules (e.g. CW004 migrations, Go method
  sets, Java overloads) live in the adapter. Go is the first non-Python adapter because it proves
  the architecture with the strictest semantics and the simplest oracle (`go build`).
- **V6 — Conservative by construction.** Resolution stays tri-state (`valid`/`broken`/`unknown`);
  `unknown` is never reported as a conflict, and reports say which parts were not analysed.
  Precision ≥ 95 % is a release gate; recall ≥ 80 % is measured only over *officially supported
  conflict types*, listed per language in `docs/languages/<lang>.md`.
- **V7 — Bounded combinatorics with honest coverage.** Every N-way result carries
  `coverage: "complete" | "bounded"` plus the bound that was hit (`--max-trials`, candidate
  limits). Unchecked combinations are reported as unchecked, never as safe.
- **V8 — Agent-native "intent claims" and an MCP server move to post-1.0.** They were on my
  earlier roadmap, but the vision rightly puts core usefulness first; integration with
  orchestrators goes through the stable CLI/JSON contract in v1.0.
- **V9 — Owner approval gates.** Public GitHub repository, PyPI releases, publishing the
  GitHub Action, contacting external teams for feedback, and installing additional toolchains
  (Node/TypeScript, a full JDK, PHP) on this machine require the owner's explicit permission.
  The architect will ask at the stage that needs it (toolchains: v0.4/v0.6; publication: v0.9).

## 4. v1.0 scope

**Mandatory**

1. N-branch: combined check, plan (orders, `together` groups, blocked reasons, explanations,
   up to 3 materially different alternatives), minimal culprit sets, coverage reporting,
   order independence; scenarios with ≥ 5 branches in the acceptance suite.
2. Five languages (Python, TS/JS, Go, Java, PHP), each with: symbol removal/rename, incompatible
   signature changes (language-appropriate: arity/keywords, overload sets, exported/visibility
   changes), broken imports/module links, duplicate definitions/name clashes, ≥ 1 language-specific
   rule chosen from real cases; depth documented per language; a polyglot-repo test.
3. Diagnostics: rule id, severity, branches/culprits, files, symbols, use sites, explanation,
   minimal reproduction set, remediation hint where justified, explicit limitation notes.
4. Contracts: stable JSON (published JSON Schema, versioned) and SARIF; documented exit codes;
   GitHub Action; incremental cache; read-only guarantee; Python 3.11–3.14.
5. Quality report per `docs/QUALITY.md`: precision ≥ 95 % (gate), recall ≥ 80 % over supported
   types (gate, or an honest miss with measured numbers and a plan, decided by the architect
   with the owner), per language and per rule, semantic separate from textual.
6. Performance report: 5/10/30 branches × small/medium/large repos, cold/warm, p50/p95, peak
   memory; budgets fixed after the v0.4 baseline; no critical known defects.
7. Docs: quickstart, real conflict gallery, per-language depth pages, contracts.

**Optional (post-1.0 unless they come cheap)**

Cross-language contracts (OpenAPI, Protobuf, GraphQL), C++ via `compile_commands.json`,
intent claims / MCP server, PR-comment bot, LSP/IDE, auto-fix suggestions as patches,
build-graph awareness for monorepos (Bazel/Nx), managed/hosted service.

## 5. Release sequence

Each release must give users something they can verify; numbers do not advance for refactors
alone.

| Release | User value | Content |
| --- | --- | --- |
| v0.3 | Safe merge order for many Python branches | v0.3b: `plan`, target references, precise CW005 culprits, one finding per use site, batched git I/O, step explanations, coverage field |
| v0.4 | Trustworthy numbers | evaluation harness + labelled corpus (Python), holdout set, precision/recall per rule, perf baseline 5/10/30; remediation hints; JSON Schema; quickstart + conflict gallery |
| v0.5 | Second language, same guarantees | `LanguageAdapter` refactor (Python moved behind it, outputs byte-identical), Go adapter (`crosswire[go]`), polyglot test, Go corpus |
| v0.6 | Web stacks | TypeScript/JavaScript adapter (ESM/CJS, `tsconfig` paths, barrels, type-only exports) |
| v0.7 | JVM | Java adapter (packages, imports, overload sets, visibility) |
| v0.8 | PHP | PHP adapter (namespaces, PSR-4 via `composer.json`, `use` statements) |
| v0.9 (beta) | Ready for outside users | planner alternatives + bounded combinatorics hardening, 5/10/30 perf budgets, full quality report, independent field validation per language, external feedback (owner approval) |
| v1.0 | Stable | all mandatory criteria in §4 met, contracts frozen, no known critical defects |

## 6. Team model

Opus 5.5 — architecture, contracts, roadmap, independent reviews, acceptance, technical debt,
release readiness. Terra — implementation. Sol — tests, corpus, independent measurement.
To keep measurement honest, **Sol owns the corpus and the holdout split; Terra never sees the
holdout** (§ QUALITY.md). Each stage starts with a written design review by Terra and Sol.
