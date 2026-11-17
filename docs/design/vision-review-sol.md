# Vision / QUALITY review (Sol)
The methodology is sound; the full five-language corpus is a staged v1.0 deliverable,
not a one-session task. Begin with a labelled Python pilot before interpreting percentages.
Python: compileall catches syntax only; pin pyright basic diagnostics/config and supplement
with focused import/call smoke tests for runtime export behaviour pyright cannot establish.
Go: pin go build and vet; classify unrelated vet warnings separately from compiler failures.
TS/JS: pin tsc, tsconfig and dependencies; checkJs must be enabled for measured JS cases.
Java: use each project's wrapper, classpath and JDK; javac without dependencies is not an oracle.
PHP: php -l catches syntax only; pin PHPStan/config/stubs and retain diagnostic identifiers.
All oracles need target + every tip green under identical configuration, a textually clean
native integration, and an attributable diagnostic; environment failures stay unlabelled.
Start with 30–50 Python positives and 3 controls per positive across at least 5 repositories.
The v1.0 minimum 150/450 per language is reasonable, but aim for 8–10 repositories so
repository-level holdout stratification has useful size/rule diversity; report every empty cell.
Precision on a 1:3 constructed mix is prevalence-dependent; publish live-PR precision separately.
Define one-to-one finding/diagnostic matching and recall's denominator before collecting labels;
extra predictions are FP, duplicate oracle diagnostics are not extra independent positives.
Commit only the hash of a canonical private holdout manifest before tuning; keep its cases,
labels, SHAs and raw diagnostics outside shared workspaces and never send them to Terra.
Publish only aggregate holdout metrics; a separate public development corpus remains debuggable.
Repository splits alone do not prevent template leakage: reserve mutation families/time ranges
and freeze supported-type lists, tool versions and split seeds before evaluation.
Mined “fix build within 48h” commits are candidates, not labels: replay and verify both parents.
Report Wilson intervals plus clustered uncertainty by repo; audit every FP and an independent
10% of labels. Predeclare budgets and record peak-RSS units/platform before performance gates.
