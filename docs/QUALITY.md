# crosswire — independent quality and performance methodology

Status: ADOPTED (architect). Owner of the corpus and measurements: Sol. Auditor: Opus 5.5.
Implementation (Terra) never sees the holdout set.

## 1. What a "semantic conflict" is (ground truth)

A set of branches `S` against target `T` has a **semantic conflict** iff:

1. `T` and every branch in `S` pass the oracle on their own;
2. `git merge-tree` integrates `S` without textual conflicts; and
3. the oracle fails on the integrated state with an error in a **supported conflict type**
   (per language, `docs/languages/<lang>.md`), attributable to the interaction of ≥ 2 branches.

Textual conflicts (CW005) are measured separately and never counted towards semantic metrics.

**Oracles** (evaluation harness only, never runtime deps):

| Language | Oracle |
| --- | --- |
| Python | `pyright` (basic mode, unresolved import / attribute / call errors) + `python -m compileall` |
| Go | `go build ./... && go vet ./...` |
| TypeScript/JS | `tsc --noEmit` (project `tsconfig`), JS via `checkJs` where configured |
| Java | `javac` over the module's sources with the project's classpath (Gradle/Maven `compileJava` when available) |
| PHP | `php -l` + `phpstan` level 0 (undefined class/function/method, argument count) |

## 2. Corpus

For every language, three strata, built by Sol with fixed seeds and recorded commit SHAs:

1. **Mined history.** Merge commits in real repositories where both parents pass the oracle and
   the merge fails it (or a "fix build/merge" commit follows within 48 h). Replay the parents as
   branches against their merge-base.
2. **Mutation scenarios on real repositories.** Scripted, semantics-aware edits on real code:
   rename / delete / move a symbol, add a required parameter, change visibility, remove a
   re-export, on one branch; a real-looking new use site on another; N-way variants
   (conjunctive removal, fix-by-third-branch, 5-branch mixes). **Controls** — compatible changes
   (optional parameter, unrelated edits, both sides renamed consistently) — at ≥ 3 controls per
   positive, so precision is measured against realistic noise.
3. **Live PR snapshots.** Open PRs of active projects (as in `docs/validation/v0.2.md`) for
   false-positive rates in the wild; positives confirmed by the oracle on the virtual merge.

Labels come from the oracle, never from crosswire. Each language: ≥ 5 repositories of different
sizes, ≥ 150 positive scenarios and ≥ 450 controls before v1.0 (smaller pilot sets are fine
for intermediate releases, reported as such).

**Holdout.** Scenarios are split 70/30 by repository (not by scenario) with a fixed seed. The
holdout manifest's SHA-256 is committed in `docs/validation/holdout.sha256` before any tuning;
reported metrics are holdout-only. Terra may use the development split.

## 3. Metrics

- Precision and recall per language × rule, plus micro-averages; 95 % Wilson intervals;
  sample sizes; semantic and textual reported separately.
- A crosswire finding matches a positive if it names a culprit set and a use site that the
  oracle error confirms (same file and symbol). Extra findings on a positive scenario count as FP.
- Gates for v1.0: precision ≥ 95 % (lower CI bound reported), recall ≥ 80 % over supported types.
- Every miss and every FP gets a one-line root cause; recurring causes become tasks.
- The architect audits a random 10 % of labels and all FPs before a release.

## 4. Performance

- Fixed hardware: this machine (Apple M5, 16 GB), recorded in every report with OS, Git and
  Python versions.
- Matrix: branches {5, 10, 30} × repositories {small ≈ 1k files, medium ≈ 10k, large ≈ 50k} ×
  {cold, warm cache} × modes {pairwise, combined, plan}; 5 runs, p50/p95 wall time and peak RSS.
- Bounded combinatorics: report trials performed vs. `--max-trials` and `coverage`.
- Budgets are fixed in v0.4 from the baseline; later releases must not regress > 10 % without an
  architect waiver recorded in the release notes.

## 5. Reliability checks (every release)

Read-only guarantee (HEAD, index, worktree, refs byte-identical), odd git states (detached HEAD,
shallow clone → clear error, worktrees, unborn branches, submodules ignored), unsupported or
unparsable sources → `unknown` and a warning, Python 3.11–3.14, deterministic outputs across runs.

## Amendment Q1 (architect, after `docs/design/vision-review-sol.md` and `vision-review-terra.md`)

Overrides the sections above where they differ.

1. **Oracles are pinned full checkers, not syntax checks.** Python: pinned `pyright` (basic mode,
   pinned config) plus focused import/call smoke tests for runtime export behaviour pyright cannot
   establish; `compileall` is dropped as an oracle. PHP: pinned PHPStan with config and stubs,
   diagnostic identifiers retained; `php -l` alone is not an oracle. Java: the project's own
   wrapper (Gradle/Maven), classpath and JDK; bare `javac` without dependencies is not an oracle.
   Go: pinned `go build`; `go vet` warnings unrelated to the change are classified separately.
   TS/JS: pinned `tsc`, `tsconfig` and dependencies; JS cases count only with `checkJs` enabled.
   Oracle configuration is identical for target, every tip and the integrated state;
   environment failures are **unlabelled**, never negatives.
2. **Staging.** v0.4 is a **Python pilot**: 30–50 positives, 3 controls per positive, ≥ 5
   repositories. The v1.0 minimum stays 150 positives / 450 controls per language, from 8–10
   repositories per language so repository-level holdout stratification is meaningful. Every
   empty language × rule cell is reported as empty.
3. **Matching is predeclared** before any label is collected (`docs/validation/matching.md`):
   one-to-one matching of findings to oracle diagnostics; recall's denominator = distinct
   attributable oracle diagnostics in supported types; duplicate diagnostics of one root cause are
   one positive; unmatched findings are FP.
4. **Prevalence.** Precision on the constructed 1:3 mix and precision on live PR snapshots are
   published separately; only the latter describes what users will see.
5. **Holdout handling.** The canonical holdout manifest (cases, labels, SHAs, raw diagnostics)
   lives **outside the shared workspace** in `~/.crosswire-holdout/` (owned by Sol); only its
   SHA-256 is committed. Only aggregate holdout metrics are published; a separate public
   development corpus stays debuggable. Besides the repository split, whole mutation families
   and time ranges are reserved for the holdout. Supported-type lists, tool versions and split
   seeds are frozen before the first evaluation. Terra and the implementation never read that path.
6. **Mined history gives candidates, not labels:** both parents and the merge are replayed through
   the oracle before a case enters the corpus.
7. **Statistics and gates.** Wilson intervals plus repository-clustered (bootstrap) intervals.
   Precision gate: point estimate ≥ 95 % **and** lower 95 % bound ≥ 90 %. Recall gate: point
   estimate ≥ 80 % over supported types. A cell with < 20 predictions or < 20 positives is
   reported as *insufficient data* and cannot pass a gate. A language cannot pass with zero findings.
8. **Coverage honesty.** A missing language extra, an unsupported build context (Go build tags,
   TS path aliases it cannot resolve, Java without classpath) is reported as a coverage gap in
   the output, never as success.
9. Performance budgets are predeclared at the end of v0.4 with platform and peak-RSS units recorded.
