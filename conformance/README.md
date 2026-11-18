# Adapter conformance kit (S16)

Run the full Python kit against an installed crosswire, from the repository root:

```sh
uv sync --locked --group eval
uv run --group eval python -m conformance.run --output /tmp/crosswire-conformance
```

Use a fresh output directory; evidence is never overwritten. The default detector and checker are installed in the current interpreter's environment. `--detector-python /path/to/wheel-venv/bin/python` can target an independently installed wheel; `--checker-python .venv/bin/python` keeps the checker in the eval environment. The product runs as `python -I -m crosswire` in a separate process, without injected `PYTHONPATH` or imports of its implementation by the kit. This is conformance testing, not corpus measurement or a natural-positive cohort.

`templates/*.json` contains eight neutral templates and 16 explicit cases: rename, delete, move module, arity, conjunctive removal, repair by a third branch, wildcard-open exports and dynamic-open exports, each with a compatible control. Templates declare independent target-based branches, logical modules/declarations/use-site IDs, edits, language-contract mappings, expected verdicts for pairwise/combined/plan, and the complete set of oracle-failing subsets. There is no source code or filename extension in the templates. `render/python.py` supplies Python syntax and site maps; rendering the same input produces identical source bytes and commit IDs, independent of output directory.

The shared contracts are topology, binding/use identity, edit intent, valid/broken/unknown verdicts, oracle state truth, minimal causes and safe planner prefixes. Renderers own syntax, paths, parameter/call representation, source-root conventions and language-specific evidence. A future Go renderer must explicitly refuse capabilities without a supported counterpart: guarded conjunctive removal is deferred GO-5; Python wildcard/dynamic exports have no Go mapping. They must not become passing Go cases. The pilot renderer deliberately supports independent target-based branches only; unsupported operations/topologies fail explicitly.

Pyright **1.1.407** comes from the locked eval group, with a fixed basic configuration. Its actual engine version, Python package version, interpreter bytes, actual Node executable/version and npm engine/typeshed hash are recorded. Target, every branch tip and every subset use the same configuration and complete source scope. Every rendered use is also executed in an isolated focused runtime probe, which validates export behavior beyond the checker's static model. Baseline/tips must pass. A checker crash, missing dependency, wrong version, incomplete file count, unexpected diagnostic category/site, or disagreement between the oracle and declared subset truth is a **kit bug (exit 2)**. No detector result for that case can turn it into a pass; expectations are never learned from product output.

Open-namespace boundary cases and their unrelated-use controls are oracle-valid while the language contract requires conservative `unknown`: changed open exports remain a coverage gap even when the runtime use is compatible. These cases require an explicit open-module limitation and zero findings in every mode. They are not semantic positives or evidence of completeness. Closed compatible controls require `valid`; unknown coverage cannot conceal a missed supported conflict.

Conjunctive removal requires all proper subsets to pass; pairwise is valid while combined and plan expose the three-branch break. The repair template has a failing remove+use pair, but the full state passes after the third branch restores the binding. Pairwise must retain the error; combined must retain a warning with `resolved_by`; plan must place every accepted step on an independently green oracle prefix. Every planner branch must be placed or explicitly blocked. CW005, skipped integration, extra/unrelated findings, wrong source occurrence or inexact small-case culprit evidence fail conformance.

Each case directory records `rendered.json` (template hash, expected verdicts and exact generated file contents/edits), `oracle.json` (verdicts, diagnostics, runtime results and source hashes beside those contents), `detector.json` (three CLI results), and `result.json`. Top-level `provenance.json` hashes the installed detector and kit apparatus; `summary.json` distinguishes pass, detector failure (exit 1), kit bug (exit 2), and an intentionally partial `--case` selection. Private local path prefixes are tokenized in evidence; source bytes and declarations are not scrubbed or re-recorded. The run fails if the installed detector, checker or kit changes during execution. Repository HEAD/index/refs/config/worktree are checked independently around product invocations.

Fast CI command:

```sh
uv run --group eval pytest -q tests/test_conformance.py
```

It checks all renderer inputs, deterministic native Git identities, fail-closed oracle/version handling, unknown suppression, unsafe planner prefixes, immutable evidence, and an installed-product subset (`rename-conflict`, `arity-control`: eight oracle states, six mode checks). CI installs the eval group so that subset cannot silently skip. The full 16-case command remains separate. A selected-case run reports `partial`, never full-kit acceptance. These are small contract fixtures; they do not establish real-world precision/recall, implement a language adapter, or replace release suites and performance gates.
