# v0.5 mutation development corpus — Deneb

**Mutation / development only.** These numbers are never mixed with natural recorded merges, concurrent PRs or holdout data. No release acceptance is claimed. No src edits, real holdout access, sealed-file edits or project commits were performed by this task.

The installed detector is built from Git `94a7417a1ed6907e3cb3f39d30b8df59de5cf77c`, independently matched to its package bytes. Labels use pinned Pyright 1.1.407 and unchanged frozen M3 delta identities, before detector execution. Freeze SHA-256 `e5dcc02bdd6ef13f874d323d3e6d0a838c1a407e707fa1d40047d41656621a53`; selection SHA-256 `2fa8759e393521e2bb04f067f51772702e58be3c36849a0a19c27a4a4ba5e0c6`. See [freeze](mut-v05-freeze.json), [selection](mut-v05-selection.json), [full aggregate](mut-v05.json).

Repositories and sites were preregistered before builds/labels; seed `mut-v05-v1` sorts actual module-level declaration/module candidates by SHA-256. S17 prior eligible baselines inform the first three repositories; the fixed two additions were chosen by declared dependency-light structure, never mutation outcomes. No post-label replacement or apparatus tuning.

| Repository / domain | URL | SHA |
| --- | --- | --- |
| sniffio / async runtime detection | https://github.com/python-trio/sniffio.git | `22387baf7d5417842c0c2030ef860cae7c8f3a7a` |
| iniconfig / INI parsing | https://github.com/pytest-dev/iniconfig.git | `2502e28b194aa08825b2d52b7b089b3cd77df04f` |
| pytest-repeat / test execution control | https://github.com/pytest-dev/pytest-repeat.git | `1b6c199f87fd547e50d7214923f84624b7cff6c2` |
| certifi / TLS trust data | https://github.com/certifi/python-certifi.git | `ca446ca404ff3b962a0193f36e03d1eabb231968` |
| trove-classifiers / package taxonomy | https://github.com/pypa/trove-classifiers.git | `bc832553ebe6114e7682f09bc59bda6552da37cd` |

S16 templates seed real rename/delete/signature/module-move mutations and open-boundary controls. Conjunctive and repair baselines explicitly copy the original actual module for an independent fallback; these are **augmented mutation** cases, not unchanged-upstream/natural incidents or fabricated function bodies. Five-branch mixes contain the actual producer/consumer conflict plus three independent documentation edits. Typed Any example inputs isolate supported structural contracts; no runtime or project test-suite execution is claimed.

Pairwise ground truth comes from every pair; combined/plan use full integration. Fix-by-third can therefore be pairwise-positive and combined/plan-control. All participating tips need empty M3 deltas; uncertain identity/scope, external dependencies, new tip errors and textual conflicts stay unlabelled. All FP/FN records below are attributable root counts, not merely scenario counts.

## pairwise

Labels: {'positive': 31, 'control': 138, 'unlabelled': 23}; controls per positive: 4.451612903225806; ≥3 control requirement: **met**. Oracle-ineligible shares: 11.98%; exclusions: {'ambiguous-identity': 17, 'new-unsupported-diagnostic': 1, 'new-tip-diagnostic': 2, 'textual-conflict-or-missing-state': 3}.

| Rule / type | TP / FP / FN | Precision (Wilson 95%) | Recall (Wilson 95%) | Status |
| --- | --- | --- | --- | --- |
| Micro | 31 / 0 / 0 | 100.00% (88.97–100.00%) | 100.00% (88.97–100.00%) | sufficient counts |
| CW001 / PY-1 | 22 / 0 / 0 | 100.00% (85.13–100.00%) | 100.00% (85.13–100.00%) | sufficient counts |
| CW001 / PY-2 | 5 / 0 / 0 | 100.00% (56.55–100.00%) | 100.00% (56.55–100.00%) | insufficient data |
| CW001 / PY-3 | 0 / 0 / 0 | undefined (not estimable) | undefined (not estimable) | insufficient data |
| CW001 / PY-4 | 0 / 0 / 0 | undefined (not estimable) | undefined (not estimable) | insufficient data |
| CW001 / PY-5 | 0 / 0 / 0 | undefined (not estimable) | undefined (not estimable) | insufficient data |
| CW002 / PY-1 | 0 / 0 / 0 | undefined (not estimable) | undefined (not estimable) | insufficient data |
| CW002 / PY-2 | 0 / 0 / 0 | undefined (not estimable) | undefined (not estimable) | insufficient data |
| CW002 / PY-3 | 0 / 0 / 0 | undefined (not estimable) | undefined (not estimable) | insufficient data |
| CW002 / PY-4 | 4 / 0 / 0 | 100.00% (51.01–100.00%) | 100.00% (51.01–100.00%) | insufficient data |
| CW002 / PY-5 | 0 / 0 / 0 | undefined (not estimable) | undefined (not estimable) | insufficient data |
| CW006 / PY-1 | 0 / 0 / 0 | undefined (not estimable) | undefined (not estimable) | insufficient data |
| CW006 / PY-2 | 0 / 0 / 0 | undefined (not estimable) | undefined (not estimable) | insufficient data |
| CW006 / PY-3 | 0 / 0 / 0 | undefined (not estimable) | undefined (not estimable) | insufficient data |
| CW006 / PY-4 | 0 / 0 / 0 | undefined (not estimable) | undefined (not estimable) | insufficient data |
| CW006 / PY-5 | 0 / 0 / 0 | undefined (not estimable) | undefined (not estimable) | insufficient data |

Repository-clustered 95%: precision 100.00–100.00%, recall 100.00–100.00%; eligible repositories 5. Fewer than five clusters or empty denominators is not estimable. Cells below 20 predictions/positives remain insufficient. No development gate is evaluated.

| Repository | Cases | Labels |
| --- | ---: | --- |
| sniffio | 40 | {'positive': 7, 'control': 28, 'unlabelled': 5} |
| iniconfig | 40 | {'positive': 7, 'control': 28, 'unlabelled': 5} |
| pytest-repeat | 40 | {'positive': 7, 'control': 29, 'unlabelled': 4} |
| certifi | 36 | {'positive': 5, 'control': 27, 'unlabelled': 4} |
| trove-classifiers | 36 | {'positive': 5, 'control': 26, 'unlabelled': 5} |

Warnings (separate): {'CW003': 0, 'CW004': 0, 'CW005': 0}; resolved warnings 0; attribution {'status': 'not evaluated: pairwise implicit other_branch was not interpreted by the frozen attribution scorer', 'raw_flags_retained_in_evidence': {'labelled': 31, 'correct': 0, 'accuracy': 0.0}}. CW003 warnings and migration/textual signals never enter semantic metrics.

Every FP/FN (one line per root):

None.
## combined

Labels: {'positive': 28, 'control': 141, 'unlabelled': 23}; controls per positive: 5.035714285714286; ≥3 control requirement: **met**. Oracle-ineligible shares: 11.98%; exclusions: {'ambiguous-identity': 17, 'new-unsupported-diagnostic': 1, 'new-tip-diagnostic': 2, 'textual-conflict-or-missing-state': 3}.

| Rule / type | TP / FP / FN | Precision (Wilson 95%) | Recall (Wilson 95%) | Status |
| --- | --- | --- | --- | --- |
| Micro | 26 / 0 / 2 | 100.00% (87.13–100.00%) | 92.86% (77.35–98.02%) | sufficient counts |
| CW001 / PY-1 | 18 / 0 / 0 | 100.00% (82.41–100.00%) | 100.00% (82.41–100.00%) | insufficient data |
| CW001 / PY-2 | 3 / 0 / 2 | 100.00% (43.85–100.00%) | 60.00% (23.07–88.24%) | insufficient data |
| CW001 / PY-3 | 0 / 0 / 0 | undefined (not estimable) | undefined (not estimable) | insufficient data |
| CW001 / PY-4 | 0 / 0 / 0 | undefined (not estimable) | undefined (not estimable) | insufficient data |
| CW001 / PY-5 | 0 / 0 / 0 | undefined (not estimable) | undefined (not estimable) | insufficient data |
| CW002 / PY-1 | 0 / 0 / 0 | undefined (not estimable) | undefined (not estimable) | insufficient data |
| CW002 / PY-2 | 0 / 0 / 0 | undefined (not estimable) | undefined (not estimable) | insufficient data |
| CW002 / PY-3 | 0 / 0 / 0 | undefined (not estimable) | undefined (not estimable) | insufficient data |
| CW002 / PY-4 | 4 / 0 / 0 | 100.00% (51.01–100.00%) | 100.00% (51.01–100.00%) | insufficient data |
| CW002 / PY-5 | 0 / 0 / 0 | undefined (not estimable) | undefined (not estimable) | insufficient data |
| CW006 / PY-1 | 0 / 0 / 0 | undefined (not estimable) | undefined (not estimable) | insufficient data |
| CW006 / PY-2 | 0 / 0 / 0 | undefined (not estimable) | undefined (not estimable) | insufficient data |
| CW006 / PY-3 | 0 / 0 / 0 | undefined (not estimable) | undefined (not estimable) | insufficient data |
| CW006 / PY-4 | 0 / 0 / 0 | undefined (not estimable) | undefined (not estimable) | insufficient data |
| CW006 / PY-5 | 1 / 0 / 0 | 100.00% (20.65–100.00%) | 100.00% (20.65–100.00%) | insufficient data |

Repository-clustered 95%: precision 100.00–100.00%, recall 84.62–100.00%; eligible repositories 5. Fewer than five clusters or empty denominators is not estimable. Cells below 20 predictions/positives remain insufficient. No development gate is evaluated.

| Repository | Cases | Labels |
| --- | ---: | --- |
| sniffio | 40 | {'positive': 6, 'control': 29, 'unlabelled': 5} |
| iniconfig | 40 | {'positive': 6, 'control': 29, 'unlabelled': 5} |
| pytest-repeat | 40 | {'positive': 7, 'control': 29, 'unlabelled': 4} |
| certifi | 36 | {'positive': 4, 'control': 28, 'unlabelled': 4} |
| trove-classifiers | 36 | {'positive': 5, 'control': 26, 'unlabelled': 5} |

Warnings (separate): {'CW003': 0, 'CW004': 0, 'CW005': 0}; resolved warnings 4; attribution {'labelled': 26, 'correct': 26, 'accuracy': 1.0}. CW003 warnings and migration/textual signals never enter semantic metrics.

Every FP/FN (one line per root):

- `06e9c19f58ae8eff4b8b` (pytest-repeat) FN CW001/PY-2: move_module/scenario: native module removal is found pairwise as pytest_repeat.TestCase; combined omits the removed-module use of this imported/re-exported binding (zero findings; partial coverage)
- `4f2f5550a7619ba7d1bf` (trove-classifiers) FN CW001/PY-2: move_module/scenario: native module removal is found pairwise as trove_classifiers.Dict; combined omits the removed-module use of this imported/re-exported binding (zero findings; partial coverage)
## plan

Labels: {'positive': 28, 'control': 141, 'unlabelled': 23}; controls per positive: 5.035714285714286; ≥3 control requirement: **met**. Oracle-ineligible shares: 11.98%; exclusions: {'ambiguous-identity': 17, 'new-unsupported-diagnostic': 1, 'new-tip-diagnostic': 2, 'textual-conflict-or-missing-state': 3}.

| Rule / type | TP / FP / FN | Precision (Wilson 95%) | Recall (Wilson 95%) | Status |
| --- | --- | --- | --- | --- |
| Micro | 26 / 0 / 2 | 100.00% (87.13–100.00%) | 92.86% (77.35–98.02%) | sufficient counts |
| CW001 / PY-1 | 18 / 0 / 0 | 100.00% (82.41–100.00%) | 100.00% (82.41–100.00%) | insufficient data |
| CW001 / PY-2 | 3 / 0 / 2 | 100.00% (43.85–100.00%) | 60.00% (23.07–88.24%) | insufficient data |
| CW001 / PY-3 | 0 / 0 / 0 | undefined (not estimable) | undefined (not estimable) | insufficient data |
| CW001 / PY-4 | 0 / 0 / 0 | undefined (not estimable) | undefined (not estimable) | insufficient data |
| CW001 / PY-5 | 0 / 0 / 0 | undefined (not estimable) | undefined (not estimable) | insufficient data |
| CW002 / PY-1 | 0 / 0 / 0 | undefined (not estimable) | undefined (not estimable) | insufficient data |
| CW002 / PY-2 | 0 / 0 / 0 | undefined (not estimable) | undefined (not estimable) | insufficient data |
| CW002 / PY-3 | 0 / 0 / 0 | undefined (not estimable) | undefined (not estimable) | insufficient data |
| CW002 / PY-4 | 4 / 0 / 0 | 100.00% (51.01–100.00%) | 100.00% (51.01–100.00%) | insufficient data |
| CW002 / PY-5 | 0 / 0 / 0 | undefined (not estimable) | undefined (not estimable) | insufficient data |
| CW006 / PY-1 | 0 / 0 / 0 | undefined (not estimable) | undefined (not estimable) | insufficient data |
| CW006 / PY-2 | 0 / 0 / 0 | undefined (not estimable) | undefined (not estimable) | insufficient data |
| CW006 / PY-3 | 0 / 0 / 0 | undefined (not estimable) | undefined (not estimable) | insufficient data |
| CW006 / PY-4 | 0 / 0 / 0 | undefined (not estimable) | undefined (not estimable) | insufficient data |
| CW006 / PY-5 | 1 / 0 / 0 | 100.00% (20.65–100.00%) | 100.00% (20.65–100.00%) | insufficient data |

Repository-clustered 95%: precision 100.00–100.00%, recall 84.62–100.00%; eligible repositories 5. Fewer than five clusters or empty denominators is not estimable. Cells below 20 predictions/positives remain insufficient. No development gate is evaluated.

| Repository | Cases | Labels |
| --- | ---: | --- |
| sniffio | 40 | {'positive': 6, 'control': 29, 'unlabelled': 5} |
| iniconfig | 40 | {'positive': 6, 'control': 29, 'unlabelled': 5} |
| pytest-repeat | 40 | {'positive': 7, 'control': 29, 'unlabelled': 4} |
| certifi | 36 | {'positive': 4, 'control': 28, 'unlabelled': 4} |
| trove-classifiers | 36 | {'positive': 5, 'control': 26, 'unlabelled': 5} |

Warnings (separate): {'CW003': 0, 'CW004': 0, 'CW005': 0}; resolved warnings 0; attribution {'labelled': 26, 'correct': 26, 'accuracy': 1.0}. CW003 warnings and migration/textual signals never enter semantic metrics.

Every FP/FN (one line per root):

- `06e9c19f58ae8eff4b8b` (pytest-repeat) FN CW001/PY-2: move_module/scenario: native module removal is found pairwise as pytest_repeat.TestCase; plan omits the removed-module use of this imported/re-exported binding (zero findings; partial coverage)
- `4f2f5550a7619ba7d1bf` (trove-classifiers) FN CW001/PY-2: move_module/scenario: native module removal is found pairwise as trove_classifiers.Dict; plan omits the removed-module use of this imported/re-exported binding (zero findings; partial coverage)

Evidence follows D-Ev1: `~/.crosswire-evidence/mut-v05-evidence.tgz`, SHA-256 `c0ca51944c3e44c5095206bd025408bf5af56dcbddfac46c942ea1681803b274`; sanitized tar headers, portable JSON paths, no Git configuration/alternates. Only compact selection/freeze/aggregate are committed; release upload remains Polaris's responsibility. Raw source states, M3 identities, exclusions, detector output and case-level matches stay in the external asset.

Execution uses the immutable installed wheel as a subprocess, pairwise/combined/plan with cache disabled. Protected fixture HEAD/index/refs/config/worktree snapshots are verified. Oracle dependencies are separately frozen without installed selected repositories, avoiding site-packages fallback after module movement. Original S17/M3 and sealed holdout apparatus remain untouched. Complete stability flags and evidence hashes are in the aggregate. Independent Vega sample/all-FP audit remains pending.

## Post-label M2 scoring audit

**The inherited PY-2 scoring defect was found after labelling.** Primary metrics above implement only the predeclared M2 missing-module + use-file key. Original code, frozen labels, detector bytes and raw scores are retained; no detector or oracle run and no relabel was performed for this correction. The separately hashed/tested adapter is applied to every eligible mutation and S17 journal. Non-PY-2 matching is asserted unchanged case-by-case. Vega audit remains pending.

| Mode | Frozen raw TP / FP / FN | M2-corrected TP / FP / FN | Raw precision / recall | Corrected precision / recall |
| --- | --- | --- | --- | --- |
| pairwise | 26 / 5 / 5 | 31 / 0 / 0 | 83.87% / 83.87% | 100.00% / 100.00% |
| combined | 23 / 3 / 5 | 26 / 0 / 2 | 88.46% / 82.14% | 100.00% / 92.86% |
| plan | 23 / 3 / 5 | 26 / 0 / 2 | 88.46% / 82.14% | 100.00% / 92.86% |

S17: all 120 journals reviewed with the same adapter (six eligible controls); effect **none**; raw {'tp': 0, 'fp': 0, 'fn': 0} and corrected {'tp': 0, 'fp': 0, 'fn': 0}. Its original aggregate/labels/evidence are unchanged. Detailed pins, score differences and correction source/test hashes: [M2 audit](mut-v05-m2-audit.json). The correction is a transparent scoring-contract repair, not post-outcome policy selection.

Additional measurement limits: pairwise attribution is **not evaluated** because its JSON uses implicit `other_branch`, while the frozen scorer read explicit `culprits`; raw flags are retained and are not interpreted as 0% accuracy. This M2-only correction does not repair that separate attribution scorer. Five-branch mixes exercise branch count with three inert documentation branches, not five heterogeneous semantic edits. Only one conjunctive PY-5 case survived oracle eligibility; the other selected conjunctive scenarios remain excluded, with no replacement. No source or matching change is made to improve these gaps.

## Validation and coverage limits

Original pre-label synthetic tests passed before the frozen run; five M2 correction tests pass. Fast mutation/metadata checks: **13 passed / 9 skipped** when optional oracle and external evidence are absent; extracted archive evidence + M2 tests: **8 passed**. All 192 raw/corrected journal hashes, labels and detector bytes were checked. There are 576 mode journals and 507 eligible detector executions, not 576 detector successes. All five pinned upstream trees contain no `.pyi` files. The published archive contains both unchanged raw journals and corrected scoring views.

Pairwise Wilson precision lower bound is **88.97%** and combined/plan **87.13%** despite 100% point precision, so these samples do not meet the 90% lower-bound quality threshold; the stratum remains development-only. Resampling just five small, constructed repository clusters can yield degenerate precision intervals; these are descriptive and do not erase Wilson/sample limitations. PY-3 is empty, most rule/type cells are below 20 observations, and 23/192 cases remain unlabelled. Only one conjunctive PY-5 scenario is eligible. No post-label renderer or selector change was made to increase coverage.

The two combined/plan misses both involve module deletion with an imported/re-exported name (`pytest_repeat.TestCase`, `trove_classifiers.Dict`): pairwise emits CW001, combined/plan emits nothing with partial coverage. These observed gaps should be handed to Altair as independent regressions; the measurement task makes no runtime fix. Pairwise attribution remains unmeasured as disclosed in the audit section.
