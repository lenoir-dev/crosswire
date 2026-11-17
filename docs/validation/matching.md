# Predeclared diagnostic matching (Sol; QUALITY Q1)

This protocol is frozen before labelling the v0.3 public exploratory PR cohort.
It also governs the v0.4 pilot unless the architect records an amendment before evaluation.
Public field cohorts are development data, never holdout; no private holdout case is disclosed.

1. Pin the checker, interpreter, dependencies and full configuration. Run the same
   oracle on the target, every participating tip and the native integrated state.
   Textual conflicts, missing dependencies, unsupported configurations and non-green
   parents are unlabelled for semantic ground truth; record their exclusion reasons.
2. A semantic positive requires green target and tips, textually clean integration,
   and a new attributable supported diagnostic or a focused runtime assertion.
   A nearby “fix build” commit or crosswire output is candidate evidence, never a label.
3. Normalize diagnostic identity to (supported type, repo-relative path, fully-qualified
   symbol). Collapse repeated diagnostics caused by one root cause. Match a prediction
   only if its use-site file, symbol and culprit branches are confirmed by the oracle.
   Line shifts are permitted; a different symbol or owner file is not a match.
4. Match one-to-one: one prediction claims at most one attributable diagnostic and
   vice versa. An unmatched prediction is FP only on an oracle-eligible evaluated
   state; uncertain/environment cases stay unlabelled, not negative controls.
5. Recall denominator = distinct attributable supported oracle root causes. Extra
   predictions on a positive are FP. Deduplicated T12 uses in one file are one
   prediction; retain the constituent oracle diagnostics for audit without multiplying TP.
6. CW005 is excluded from semantic counts. CW003/CW004 warnings are not validated
   merely because two ASTs/files differ: require the declared name/migration oracle.
7. Report each rule's TP, FP, unlabelled and number of eligible predictions. Empty
   cells and cells with fewer than 20 predictions/positives are insufficient data.
   Precision = TP/(TP+FP) only over eligible predictions; provide Wilson intervals.
   One-repository exploratory runs cannot support repository-clustered intervals.
8. Keep live-PR, mutation and mined-history metrics separate. Holdout manifests and
   diagnostics stay outside the workspace in the Q1-private location; only a canonical
   manifest hash and aggregate holdout results may be published after the split is frozen.
