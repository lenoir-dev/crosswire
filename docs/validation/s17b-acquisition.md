# S17b authorized acquisition — Deneb

**Acquisition incomplete; development only; measurement not run.** Exactly one invocation ran from a clean `git archive` of `89df44070c7dfe2b39b05343d3884461359aba58`, with checkpoint (1) and Polaris’s matching authorization. Detector revision stayed `30ff34363070175160e066dd1b5743856c907a05`. No retries, substitutions, date/seed/policy changes, src edits or project commits. The sealed holdout was never accessed.

The metadata walk stopped on its 14th GET, a failed first-repository timeline request. The frozen adapter records the failed claim but discards the subprocess exit/stderr, so the exact HTTP/transport cause is unavailable; no diagnostic retry was made. No configured request/transfer ceiling was exhausted. Its generic downstream reason `acquisition-incomplete-at-ceiling` must not be interpreted as evidence of hitting a ceiling. The frozen global failure rule left the remaining seven repositories unattempted. Two commit-list GETs still acquired the retained slot’s graph.

**16 GETs total: 14 metadata, 2 commit-list, 1 failed request included.** Metadata evaluated two ranked pairs out of 29, selected one, and left a 27-pair ranked tail unattempted. The selected pair failed frozen B2 `integrated-earlier-pr` contamination before any oracle: one structural exclusion/unlabelled pair, zero graph-ready pairs. It is not a control or a natural positive. No precision/recall, label, detector accuracy or prevalence estimate exists.

| Repository | Metadata GET / 127 | Commit GET / 60 | Metadata pairs evaluated | Selected | Graph evaluated | Graph-ready | Git bytes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| pytest-dev/iniconfig | 14 | 2 | 2 | 1 | 1 | 0 | 235,926 |
| python-trio/sniffio | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| pytest-dev/pytest-repeat | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| pytest-dev/pluggy | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| python-trio/outcome | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| python-hyper/h11 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| pallets-eco/blinker | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| pallets/itsdangerous | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

Transfer accounting: **235,926 bytes** against 2,147,483,648 allowed; the initial default-history fetch accounts for these bytes and the two head fetches add zero new objects/progress-estimated bytes. This is the authorized max(object-store growth, progress bytes) proxy, not a wire-byte guarantee. The single acquisition returned exit 1 after about 101 seconds. Per-repository requests and both non-rolling sub-budgets stayed within policy.

Checkpoint (2) material is at **`~/.crosswire-evidence/s17b/checkpoint-2.json`**, with referenced files under **`~/.crosswire-evidence/s17b/checkpoint-2-material`**. SHA-256: `159fbdd2d0882263e5548d3a2be0f93974c1e6c50b29a5dc61f206c6911bcaa8`. It binds selected pairs and object SHAs, metadata/rejection/structural-exclusion ledgers, an independently verified Git bundle, source/config/scope hashes, the complete existing apparatus graph, frozen M3 and the audited M2 adapter, controller Python/AST/stdlib/native runtime, Git/gh bytes/config, pinned checker environment/dependency/typeshed/Node maps, and statistics settings. All selected identities and large per-case evidence stay external under D-Ev1.

The detector wheel was built and installed **offline from git archive 30ff343**, SHA-256 `54bd04dc861e029bf92ce40975b6b51ea2b994168f03d78aa2a2a8e5c800324e`; every installed package byte and wheel member equals that committed source. The original S17 oracle environment, Pyright package/engine 1.1.407, and Node bytes match the earlier freeze. Only interpreter/package metadata and file hashes were inspected: **zero checker or detector CLI invocations, including version probes; zero case observations or labels**. No dependencies were downloaded.

This is checkpoint-(2) **material for audit**, not permission or a claim of a runnable natural measurement. The future measurement driver/journal integration is absent, and the 5,400-second enforcement remains that driver’s audited obligation. There are no graph-ready pairs to measure. Oracle first-party dependencies are retained as in S17; they were not exercised or tuned for this cohort. No integration states were constructed for the graph-excluded pair. Vega must audit the material and Polaris separately authorize any later measurement.

Sanitized archive: **`~/.crosswire-evidence/s17b-acquisition-evidence-v2.tgz`**, SHA-256 `25b99d19396a3b03abeef6977c7b6f091cb8cee90732e5fe6f64f49f787d9461` (119 members; 1,270,403 bytes). It contains portable acquisition/API records, selected/rejected/object/scope/environment manifests, the bundle, wheel, committed apparatus bytes and preparation scripts. Interpreter/Node/installed-oracle bytes are fully hashed but are not all duplicated in the archive; the recorded local environments remain available for audit. Every archive member/hash was checked, including committed source bytes; tar uid/gid/mtime are zero and uname/gname empty. No expanded local paths enter this report. Release upload belongs to Polaris.

Two local preparation issues were corrected before publishing this material: the historical environment digest requires pathlib ordering rather than string ordering, and portable artifact JSON must be distinguished from byte-identical committed source JSON. Prior preparation/archive copies remain private; acquisition and semantic evidence were never rerun or changed. The canonical portable checkpoint/hash above supersedes the raw temporary-path preparation copy.

Machine-readable aggregate: [s17b-acquisition.json](s17b-acquisition.json). Source/checkpoint/hash/archive/environment/bundle verification passed; no additional product test or measurement was run. **Stopped for Vega’s checkpoint-(2) audit and Polaris’s separate measurement authorization. No background job remains from this task.**
