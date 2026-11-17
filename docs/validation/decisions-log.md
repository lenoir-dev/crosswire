# Measurement decisions for architect review

These decisions follow PLAN-v0.4, QUALITY Q1 and matching M1; none changes product
contracts or permits implementation access to the holdout.

| Decision | Reason / evidence |
| --- | --- |
| Screen 34 candidates rather than stopping at eight; retain seven green targets. | Only 7 of 28 full checker runs passed; 5 clone failures and one missing source root were separately excluded. Diagnostics were not disabled. |
| Repository split 5 development / 2 private; seed 17042026. | Nearest-integer 70/30 on seven retained repositories; public data contains only development identities and aggregate screening results. |
| Seal canonical private labels/evidence before detector evaluation. | `holdout.sha256` covers the full private manifest, SHAs, raw checker evidence and labels. Private labels are not regenerated after development debugging. |
| Public development mutations coordinate original callers on A and preserve type-ignore comments. | Initial whole-AST rewrites dropped pragmas and produced non-green tips. Such attempts were rejected; accepted target/A/B/merge checks use the same full checker. |
| Make development compatible controls actual optional-keyword/API additions, rather than another documentation-only edit. | Keeps the three control families materially distinct: compatible API change, unrelated edit, coordinated rename. Existing private labels stay sealed and unchanged. |
| Publish all development generator revisions/exclusions. | `v04-development-flow.json` and `v04-development-exclusions.json` retain rejected/superseded searches rather than absorbing them as controls. |
| Compare AST occurrences using a canonical JSON encoding, not ast.dump. | Python 3.11 and 3.14 omit empty AST fields differently; a regression test proves cross-version identity. Match the outer named call, not a nested cast expression. |
| Pin detector measurement to Python 3.14 as well as the oracle. | Accepted real-source refactorings may contain Python 3.12+ syntax. A Python 3.11 parse limitation must not accidentally change the pilot's frozen interpreter contract. |
| Missing-module predictions at later attribute calls remain unmatched under M1. | Four public module-move cases produce a checker error at the import/module. No retrospective relaxation of the approved site/symbol matching is allowed. |
| Predictions outside pinned production roots are unlabelled, not FP/TP. | Crosswire scans repository tests too; those sites are not covered by this pilot's full production-root checker. All 36 excluded development predictions and reasons are retained; the 60% share is reported. |
| Public gallery labels are scripted real-source mutations, not mined incidents. | `eval/development/gallery.md` states this explicitly; exact upstream SHAs and both patches support independent replay. |
| Eight native merge-history candidates replayed; seven controls, one exclusion. | Base, both parents and native merge-tree were checked. No positive was inferred from a commit message or a manually resolved upstream merge commit. |
| Live PR noise uses HTTPX, Django and Flask separately from mutation precision. | 59 PR pairs, zero semantic predictions; this cannot establish semantic precision/recall or pass a gate. |
| S14 fixture uses 10% Python modules (at least 30), remainder assets. | File-count scaling is explicit; 50k files includes 5k Python modules and is not disguised as only 30 Python files. Textual checks stay enabled. |
| Declare 30-second performance timeouts and keep censored cells. | A timeout is a lower bound, not a successful sample or a missing zero. p50/p95 are null unless all five samples complete; an incomplete warmup cannot claim warm quantiles. |
| Persist each matrix cell and require identical source hashes for resume. | A large 54-cell/270-sample experiment remains reviewable after interruptions; results cannot silently mix revisions. |
| Measure Python-worker peak RSS with explicit units/scope. | Darwin reports bytes. This is not a claim about simultaneous aggregate RSS of the entire Git/Python process tree. |
| Preserve old finding semantics through explicit additive-field golden projection. | New hint/limitations/repro/coverage metadata are permitted by v0.4; changed old rule/severity/message/location fields are rejected. Re-recording waits for the architect's source boundary. |
| Final holdout, performance matrix and full suites wait for explicit src frozen. | Architect instruction; dry-runs and public development evaluation alone have run so far. |
| Preserve account budget while implementation is handed over. | Own-session rate-limit telemetry at 19:14 showed 17% remaining in the 5-hour window. No final jobs were started; S11/S12 artifacts and the resuming commands are saved. |
| Save a runnable checkpoint at the budget boundary. | At 19:26 remaining primary budget was 6%; S11/S12 are complete, 21 focused checks are green, and source-frozen final jobs remain explicitly prohibited. `v04-resume.md` records all commands and outstanding work. |

## R2 revision (Deneb, 2026-11-17)

The decisions above describe the retired r1-r3 apparatus and are historical, not
current authority. PLAN v0.4 R2 and matching M2 supersede their conflicting rows.

- Retired the old exposed holdout with a separate private marker; its files remain
  untouched and are never measured. The v0.4 runner refuses measurement outright.
- The complete screening candidate catalog is private. New screening identities
  and rejected candidates never enter shared files; only counts may be published
  after the new seal.
- Include every test/tests directory in the identical target/tip/integrated oracle
  configuration. Two old development targets fail this stronger scope; old labels
  cannot be silently promoted to R2 eligibility.
- Count detector crashes, invalid JSON and timeouts as error rows. Oracle-positive
  diagnostics remain in recall's denominator; emitted rules own prediction buckets.
- Clustered intervals are not estimable below five eligible repositories; gate
  precision against the smaller Wilson/clustered lower bound where estimable.
- A one-time target reverse-index pass is allowed by V3-05. The regression forbids
  rescanning unrelated target use sites for each integrated plan state.
- Pin the local Node/interpreter/checker artifacts by version and SHA-256. Python
  dependency distribution hashes are also required; existing installed versions
  alone are not evidence of a reproducible hashed installation.
- Shell HTTPS access to both GitHub and PyPI timed out (10-second probes). Fresh
  private clones and dependency hash resolution remain pending while offline
  harness/regression work continues. This is an infrastructure issue, not budget.
- GitHub's connected read API remained available when shell HTTPS failed. New
  private candidates were materialized from pinned upstream Python/test sources,
  stubs, pyproject and license; every fetched Git blob ID was independently checked.
  Non-source fixtures are omitted; this is a static-checker source snapshot, not a
  claim to have executed upstream test suites.
- Supplemental R2 families use explicit probe wrappers around real upstream API
  objects. Report this as an **upstream API oracle-scaffold** stratum separately
  from historical mutations of upstream declarations and from mined incidents.
  Counts of repeated mechanisms are pilot observations, not broad generalization.
- Initial R2 oracle-only generation rejected a coordinated re-export control
  because the imported name was renamed along with its local alias. r5 preserves
  the imported name; initial failed evidence is retained. Three-branch controls
  use an independent B edit to avoid accidental textual conflicts. No detector
  result or holdout measurement informed these generator repairs.
- Re-screening 96 historical development cases with tests retained 47 eligible
  cases (11 positives). Existing published r1-r3 metrics are superseded; final
  development metrics must be regenerated after source freeze.
- Disable only the pyright Python wrapper's update-version notification/network
  probe (`PYRIGHT_PYTHON_IGNORE_WARNINGS=1`); compiler diagnostics are unchanged.
- New v2 seal completed and verified: four repositories, 20 oracle positives per
  CW001/CW002/CW006, 180 controls. Hash list covers the private manifest, per-case
  repositories/refs, eval source (including revision archive), policy, matching,
  dependency lock and local toolchain pins. The aggregate screening file was
  replaced only after sealing. No detector has run against either holdout.
- Public development now retains 228 attempted cases: 179 eligible, 44 positives.
  132 supplemental cases passed static eligibility; 27 ambiguous hard-negative
  controls also passed focused runtime export checks. Historical ineligible rows
  remain listed rather than disappearing from coverage accounting.
- Offline public three-branch replay verified the exact upstream/baseline/branch
  patch path. A missing Git-diff terminator was discovered and corrected before
  sealing; an independent `git apply --check` regression preserves it.
- Final synthetic pre-commit QA found per-rule outside-scope counts being copied
  into every rule. Fixed them to use the emitted rule and added a regression;
  non-UTF8 detector output now also becomes an error/FN row instead of aborting.
- Toolchain pin includes the actual npm Pyright engine and all 5,035 bundled files
  (including typeshed), in addition to Python wrapper/Node/interpreter artifacts
  and hash-pinned Python distributions. This prevents a changed same-version
  cached checker engine from escaping the toolchain check.
- Construct-validity audit found two nominal hard-negative variants lacked their
  advertised baseline edit. r6 adds the existing init submodule re-export before
  A drops it, and the same-name declaration in another module before A removes it.
  Replaced 12 private and 9 public controls; every replacement was independently
  rechecked by the static oracle and runtime smoke. All positive case/label bytes
  were asserted unchanged. Earlier seal/evidence versions remain archived privately;
  no detector measurement or tuning informed these repairs. The final public hash
  list is r6 and is still awaiting the architect's commit before source freeze.
- Final apparatus-only focused suite: 50 passed (8.09 s). The previous broad focused
  source/contract suite passed 107 tests before the last five apparatus additions.
