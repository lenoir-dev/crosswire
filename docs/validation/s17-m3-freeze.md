# S17 M3 apparatus freeze

Status: FROZEN before repository selection, repository builds or natural labels. Synthetic oracle tests were written first (initial collection failed because implementation did not exist); final result: **29 passed**, including the actual pinned-checker non-green-baseline interaction test.

Task-start Codex 5-hour allowance: **31% remaining / 69% used**, read from the same account rate-limit backend used by `/status`. No claim of a budget block is made.

Machine manifest: `s17-m3-freeze.json`; SHA-256 **`5e7dc0bbedbc88d55dec3fb3767322b1f2cf991d30d5b2016ecebb5e7a1e2170`**. All apparatus inputs below are commit-ready; Deneb has made no commit. The runner verifies this file graph before preregistration, before measurement and after each case. No natural label existed when this document was written.

M3 uses exact `(rule, path, symbol, occurrence, root cause)` subtraction after explicit one-to-one Git rename mapping. Line offsets and checker prose never define identity. Occurrences use a location-free AST plus lexical scope; changed defining AST/context changes root cause. Repeated indistinguishable sites, shadowed bindings, failed/incomplete checker scope and missing external dependencies stay unlabelled. Every tip must have an empty delta; only a new supported attributable full-state delta is positive; no new diagnostic is a control. Newly unsupported diagnostics remain unlabelled. Attribution checks the same diagnostic delta in full and leave-one-out states, never raw checker exit status.

The fixed basic oracle is Pyright 1.1.407 on Python 3.14.8, Darwin, with complete production/test scope and identical case-union includes/extra paths for target, tips and native integration. The manifest pins Python, actual Node, checker engine/typeshed, and the entire installed oracle dependency tree. The detector is an independently installed wheel built from HEAD `f3eaa4e80c1a3f2f3bb09e3e1c24229bcb7e78d0`; its package bytes were independently matched to the Git source archive. Mutable worktree source is not the measured detector.

The natural stratum has its own policy and apparatus under `benchmarks/s17/`, outside the sealed eval tree. Eight candidate repository URLs/domains and a bounded selection rule are fixed in `policy.json`; exact public HEAD/merge SHAs are recorded by the subsequent preregistration command before any repository checker run. Unsupported stubs/context, incomplete scope and ambiguous matching are exclusions, not controls. Old development exclusions and holdout policy are untouched.

Metrics use M1/M2 emitted rule/type and one-to-one use/root-cause matching, separate attribution, Wilson intervals and whole-repository bootstrap intervals (five-repository minimum). Fewer than 20 predictions/positives is insufficient. Zero observations cannot pass a gate; every result is development-only. The detector runs only oracle-eligible cases, so an emitted-prediction rate over excluded cases is explicitly not estimable.

| Input | SHA-256 |
| --- | --- |
| `benchmarks/s17/__init__.py` | `07635675657c4d1b1db91344c1f17eca0baf5c307a7c15b928880fd9ce352272` |
| `benchmarks/s17/identity.py` | `8e17e4625222754b9d194c713b4918c7a6c90696d3c8e2fd35b3112d2ef00dc2` |
| `benchmarks/s17/m3.py` | `f9c64ecbfa9a7939303b697287a317ba84cf72d3ad23d86f17832e839f3ae5b5` |
| `benchmarks/s17/matching.py` | `643f81c6ef41b7dfedfc1c1414f320a63cad4fd6c185de553dc29ce10d537a6f` |
| `benchmarks/s17/metrics.py` | `f0d27bfd030af9ffcddf7844b77413655e797f1d7da1192f4c17a7b2d3610f5a` |
| `benchmarks/s17/oracle.py` | `db555eb21228f76285c05fb8cda68587c2b0b323ab52484c3d6c13da048e84d3` |
| `benchmarks/s17/policy.json` | `c57e2bb91504730ae5c6750b4a40c91225401c2e4356f93d1868fc2d38262730` |
| `benchmarks/s17/run.py` | `690519ba45bc1fcc801f5a40953e7520f4a9b3a753fb4d3d836fcb47168fb7eb` |
| `conformance/git.py` | `32a7d669a7bafe79e7eda4385d925e213b6c8b96906f92a11acfff9b5c4b0912` |
| `conformance/oracle.py` | `42d731e566caf99034f5aaf5b8d861cd3964a0a2817dba3fce419234c88a45a9` |
| `conformance/run.py` | `6511fb2ea071fcdf1669d2ae97c0b758c0b2edb8885a8793514cd9fd70ccb63b` |
| `tests/test_s17_identity.py` | `05bd726dcccdb9b5a69871fb4abeca5629e02d6a58d040f533df314344535aa7` |
| `tests/test_s17_m3.py` | `3d70e8d6bc6a8814d3c12afcff710937bc07e118663064302feaec75e12e4761` |
| `tests/test_s17_matching.py` | `3d574396557b173494208eec2612014918a9f531b951810fb0cadc60ed0aa13d` |
| `tests/test_s17_oracle_integration.py` | `d14ee1a42ba0a58c4aca17c38b995e4fc4da95dbf3cc8666093f8c1df60668b1` |

No source edits, sealed apparatus edits, holdout access, repository labels or commits were performed before this freeze. Any required apparatus change after natural labeling requires an explicit separate round/amendment; do not silently refresh hashes to obtain better numbers.
