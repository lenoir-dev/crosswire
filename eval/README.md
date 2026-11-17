# Independent Python pilot evaluation

This is development tooling; the product never invokes the oracle. The frozen
R2 policy is `policy.json`; M1/M2 matching is in `docs/validation/matching.md`.
Install the hash-pinned oracle dependencies from
`docs/validation/v04-oracle-requirements.lock` with `uv pip install --require-hashes`.
`toolchain.json` also pins Node, Python and the checker artifacts. Those local
binary hashes describe the measured arm64 macOS environment, not all platforms.

Screening candidate identities and individual rejected targets are private. No
candidate catalog lives in this package. Screening includes production sources,
all test directories and root-level test modules. Target, every tip and native
integrated state use identical checker configuration; environment failures remain
unlabelled. Focused runtime smoke checks validate ambiguous export controls.

The old exposed holdout is retired, untouched and never measured. A new v2 seal
lives outside the checkout. **No holdout measurement is allowed in v0.4.** Only
`python -m eval.run_holdout --verify-only` is permitted now; the future measurement
path requires explicit v0.5 authorization, a source-freeze manifest and a fresh
single-attempt marker. Same-user isolation is procedural, not an OS boundary.
`docs/validation/holdout.sha256` binds manifests, case repository state/refs, eval
code, policy, matching and toolchain/dependency pins. Polaris commits this list
and the apparatus before source freeze. Do not change sealed files afterward.

Public `development/cases.json` contains exact upstream SHAs, labels and patches.
Historical upstream-declaration mutations and supplemental **upstream API oracle
scaffolds** are distinguished. The latter wrap real API objects with explicit
probe code and are not natural upstream incidents. They cover hard negatives,
`from m import f`, class constructors and three-branch conjunctive removal.

Portable `${CACHE_*}` tokens replace host temporary paths in JSON. Host mappings
live in `~/.crosswire-eval/locations.json`, or `CROSSWIRE_EVAL_LOCATIONS`. On another
machine, materialize the public clones/cases at local paths and supply that map.
`python -m eval.replay CASE --destination NEW_DIR` recreates a public case from its
upstream and baseline/branch patches; `--source-cache CLONE` permits offline replay.
Replay's fixtures use Git mutations only inside the requested destination.

After Polaris says exactly `src frozen`, re-record approved shapes, run full
3.11/3.14 suites, development metrics and PR snapshot noise, then performance alone:

```
uv run --group eval python -m eval.run_development
uv run --group eval python -m eval.live --offline
uv run --group eval python benchmarks/perf_matrix.py --repeat 5 --timeout 30 --output docs/validation/v04-perf-matrix.json
uv run --group eval python benchmarks/perf_matrix.py --vega-scenario --repeat 5 --timeout 30 --output docs/validation/v04-vega-perf.json
uv run --group eval python -m eval.publish
```

Offline PR replay is labelled as a pinned snapshot, never current-live coverage.
Development results are optimistic and cannot pass a release gate. The matcher
uses emitted rule/type identities, module+file for PY-2, all oracle diagnostics,
and separate detection/attribution. Detector failures count as FN on positives.
Clustered intervals require five eligible repositories; stricter lower bounds
apply to future gates. Private exports allowlist both keys and values and suppress
small cells. `tests/test_eval*.py` use synthetic evidence and never read holdout.
