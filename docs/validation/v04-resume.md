# v0.4 Deneb checkpoint

R2 apparatus and corpus work completed (final seal revision r6) in this fresh session. **Waiting for the
architect's exact `src frozen` before golden re-recording or final measurements.**
No budget stop is claimed. No commits/checkouts/stashes/resets/pushes occurred in
the shared project. All Git mutations belong to isolated evaluation/test fixtures.

## Sealed holdout

- Old exposed holdout retained untouched; retirement is a separate private marker.
- New `~/.crosswire-holdout/v2/`: four repositories; 20 oracle positives each for
  CW001/CW002/CW006, 180 controls. Private candidate/rejection identities remain
  outside the shared workspace. All 240 eligible cases are sealed, unmeasured.
- `docs/validation/holdout.sha256` covers manifest, repositories/refs, eval code,
  policy, M1/M2, toolchain pins and hashed Python dependency lock.
- `docs/validation/eval-code.sha256` is the combined apparatus fingerprint.
- Architect must commit hash list + apparatus before announcing source freeze.
- `python -m eval.run_holdout --verify-only` verifies without measuring.
- **Never run holdout in v0.4.** The future v0.5 path requires separate explicit
  authorization, immutable source manifest and a single-attempt marker.
- Do not edit `eval/**/*.py`, `eval/policy.json`, `eval/toolchain.json`,
  `matching.md`, or the dependency lock after this seal without architect review;
  hash verification will fail. Tests, benchmarks and report files can still change.
- Pre-commit construct-validity repairs replaced 12 private/9 public controls. All
  positive case/label bytes were asserted unchanged. The final r6 seal was verified;
  earlier evidence/seals are archived privately. No detector/tuning informed repairs.

## Public apparatus and corpus

- Matching uses emitted rule/type identities, PY-2 module/file, all attributable
  oracle diagnostics, one-to-one occurrences and category-set agreement.
- Crashes/timeouts/malformed detector output retain positive FN and error counts.
- Rule-keyed buckets; clustered bounds require five eligible repositories and
  stricter precision lower bounds gate future valid measurements.
- Oracle includes all discovered test directories/root-level tests. No diagnostics
  were disabled. Runtime export checks cover ambiguous supplemental controls.
- New public corpus: 228 attempted cases, 179 eligible and 44 positives; historical
  ineligible rows are retained. Scaffolds are explicitly distinguished from old
  direct upstream-declaration mutations and natural mined incidents.
- Public cache tokens resolve via `~/.crosswire-eval/locations.json` (or env
  `CROSSWIRE_EVAL_LOCATIONS`); no committed JSON configs contain absolute tmp paths.
- Node/Python/checker binary versions, actual npm engine/typeshed tree and hashes: `eval/toolchain.json`;
  distributions: `docs/validation/v04-oracle-requirements.lock`.
- Local pinned oracle remains `/tmp/crosswire-v04-eval/bin/python`, pyright 1.1.407.
  Pyright update notification is disabled, not compiler diagnostics.
- Shell HTTPS timed out; the connected GitHub read API supplied pinned private
  source/test snapshots, all Git blobs verified. Non-source fixtures omitted;
  static tests checked, upstream test execution not claimed.
- `eval/development/gallery.md` has honest replayable public examples.
- Independent offline replay of `r2-public-0040` passed all three branch patches.

## Tests and final jobs

- New `tests/test_vega_v03.py`: one reproduction per V3-01..V3-13 (30 parametrized
  checks). Latest V3 + T14-T20 run: 56 passed.
- `tests/test_eval*.py`: 50 focused harness tests passed after final apparatus edits (8.09 seconds).
- Final combined focused harness + V3 + T14-T20 + projection run: **112 passed**
  in 45.45 seconds. This is a pre-freeze focused check, not the final full suite.
- `v04-source-observed.json` records a source observation only; it is explicitly
  not an architect freeze signal.
- Goldens are not re-recorded. Projection now also permits appended coverage text;
  all prior finding semantics still require the historical projection guard.

After exact `src frozen`:

```sh
uv run --group eval python tests/refresh_v04_goldens.py
uv run --group eval pytest -q
PYTHONPATH=src uv run --no-project --python /opt/homebrew/bin/python3.14 \
  --with pytest --with jsonschema==4.25.1 python -m pytest -q
uv run --group eval python -m eval.run_development
uv run --group eval python -m eval.live --offline
```

The PR run replays the previously fetched pinned open-PR cohort, explicitly not a
claim about current live heads. Field cache locations are in the external map.

Run performance alone after all oracle/test jobs finish:

```sh
uv run --group eval python benchmarks/perf_matrix.py --repeat 5 --timeout 30 \
  --output docs/validation/v04-perf-matrix.json
uv run --group eval python benchmarks/perf_matrix.py --vega-scenario \
  --repeat 5 --timeout 30 --output docs/validation/v04-vega-perf.json
uv run --group eval python -m eval.publish
```

Main matrix: 54 cells, five samples each; timeouts retained as censored bounds.
Vega scenario: 9000 Python files, 16 branches, two changed files each, warm plan
budget ≤15 s. Record full-suite results in `v04-checks.json`; publish development
as **development data, optimistic, not a gate**. Same-user holdout isolation is
procedural, explicitly disclosed. No source or performance acceptance is claimed
before the gated jobs complete.
