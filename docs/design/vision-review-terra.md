# v1 implementability review — Terra

- Freeze LanguageAdapter around immutable, language-neutral identities, spans, signatures,
  tri-state resolution and explicit coverage; keep Git/integration and reporting in core.
  Python's import, guarded-binding and migration semantics must not leak into other adapters.
- Moving Python first risks output, ordering, cache and path-resolution regressions; preserve v0.4
  goldens byte-for-byte, version adapter/cache schemas, and test mixed-language roots and collisions.
- Do not force overload sets, receiver binding or dynamic imports into a single Python-shaped
  signature. Let each adapter decide call compatibility and explain unknown outcomes.
- Pin compatible tree-sitter runtime AND grammar versions; verify wheels across Python 3.11–3.14
  and supported OS/architectures in CI, including clean core-only and each extra installation.
  Missing extras must produce explicit coverage gaps, never silent success. A lockfile alone does
  not constrain transitive versions for `pip install`; publish compatible version bounds.
- Go requires go.mod/workspace replace rules, build tags, platform files, internal visibility,
  exported names and generated code; without build context classify unresolved packages unknown.
- TS/JS needs tsconfig inheritance/paths, ESM/CJS package exports, conditional resolution,
  re-export cycles and type-only imports; JS dynamic imports and inferred member types are unknown.
- Java overloads, inheritance, classpaths, module boundaries and visibility require conservative
  candidate sets; syntactic arity alone cannot establish overload selection or absence.
- PHP needs Composer PSR-4 roots, aliases, namespaces, case rules and dynamic includes; runtime
  autoloaders and reflection must not be treated as fully resolved from syntax alone.
- Add independent adapter conformance fixtures, polyglot same-name tests and coverage by language;
  require reproducible corpus/oracle configs and make unsupported contexts visible before v1.
- V1 precision/recall gates should define confidence-bound policy, zero-finding handling and
  supported-environment coverage before release decisions; do not tune on the hidden holdout.
