# Public development measurement handoff (not holdout)

The first pinned Python 3.14 detector run has 20 detection TP, 4 FP and 4 FN over
24 positive scenarios and 72 controls. All four unmatched alerts are module moves:

| Public case | Oracle root cause / occurrence | Detector occurrence |
| --- | --- | --- |
| `python-hyper--hyperframe-016` | Missing `hyperframe.frame` at its import | `hyperframe.frame._raw_data_repr` at later attribute call |
| `pallets--itsdangerous-020` | Missing `itsdangerous.signer` at its import | later call into that module |
| `pallets-eco--blinker-020` | Missing `blinker._utilities` at its import | later call into that module |
| `pypa--trove-classifiers-008` | Missing `trove_classifiers.__main__` at its import | later call into that module |

These are not claims that the later call would work. The alerts concern real
breakage, but fail the approved strict M1 use-site/symbol match. Keep that metric
definition unchanged; consider an import-level PY-2 diagnostic for v0.5, or an
architect-approved future measurement amendment before a new evaluation round.

The mutation oracle checks the full production package and the added consumer.
Crosswire also scans repository `tests/`; 36 predictions outside those pinned
oracle roots are explicitly unlabelled, not FP/TP. Their full site/reason records
are in `v04-development-results.json`. This 60% excluded-prediction share matters
when interpreting the measured precision. No accepted control has a matched FP.

The public generator previously rewrote function bodies through `ast.unparse`,
dropping `# type: ignore` comments and causing invalid refactoring tips. Those
attempts are rejected; accepted recipes preserve comments and coordinate original
production callers. This development-only correction did not change private labels.
The harness normalizes expression fingerprints independently of `ast.dump` so
Python 3.11/3.14 agree; the detector interpreter is pinned to 3.14 for this corpus.

Private holdout identities, labels and reserved recipes are not in this handoff.
The held-out measurement will happen once after the final implementation boundary;
do not request private examples to debug these public development results.
