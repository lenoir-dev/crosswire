# S17b round-2 acquisition — Deneb

**Published incomplete; development only; no measurement.** Exactly one authorized acquisition ran from a clean `git archive` of `0b47868e5c397c6fbad860c959f8f070939e4e3a`, using the round-2 checkpoint and Polaris authorization. It returned exit 1 after 166.04 seconds. The committed policy, detector `30ff343`, selection, M3 and all graph rules stayed unchanged. No acquisition resumption, substitution, source edit, project commit or holdout access occurred. [Round 1](s17b-acquisition.md) remains published beside this report.

The first **145 GETs all succeeded (HTTP 200, exit 0)**, with no retries, waits, PR failures/stubs or exhausted ceilings. The fourth repository's PR-list response supplied a legitimate next Link using `repositories/34739117/pulls`; `next_page` preserved that numeric repository path, while `allowed_endpoint` permits only `repos/<policy owner>/<name>`. Its `ValueError` escaped repository-local `Incomplete` handling and terminated `collect_metadata`. The rejected page was never requested. This is an apparatus pagination/exception defect, not an HTTP failure, PR exclusion or semantic observation. No repair or diagnostic request was attempted.

The process failed **before writing `metadata.json`**, so the original run has no durable selected-pair or graph result. A separately archived, cache-only forensic replay recovered the three completed metadata phases: **63 evaluated pairs, 23 selected pairs**. It called only the frozen metadata/selection functions against recorded successful bodies; every first cache access matched the original 145-request order, then stopped on the same rejected Link. It had no transport, subprocess runner, graph, checker or detector. These recovered selections are explicitly distinguished from original durable output and do not authorize continuation. Pluggy's universe is partial; the remaining four repositories are unattempted.

| Repository | Metadata GET / 127 | Commit GET / 60 | Evaluated, recovered | Selected, recovered | Graph-ready | Git bytes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| pytest-dev/iniconfig | 67 | 0 | 29 | 13 | 0 | 0 |
| python-trio/sniffio | 55 | 0 | 26 | 9 | 0 | 0 |
| pytest-dev/pytest-repeat | 20 | 0 | 8 | 1 | 0 | 0 |
| pytest-dev/pluggy | 3 | 0 | 0 | 0 | 0 | 0 |
| python-trio/outcome | 0 | 0 | 0 | 0 | 0 | 0 |
| python-hyper/h11 | 0 | 0 | 0 | 0 | 0 | 0 |
| pallets-eco/blinker | 0 | 0 | 0 | 0 | 0 | 0 |
| pallets/itsdangerous | 0 | 0 | 0 | 0 | 0 | 0 |

**For every repository:** retries by cause = `{}`, completed/reserved/unconfirmed waits = 0 seconds, PR failures/stubs = 0/0, commit-list failures = 0, graph-evaluated = 0, final-head/pre-update assigned pairs = 0/0, rescue accepted/rejected = 0/0, transfer = 0 bytes. The 23 recovered selections have **unassigned head_kind**, not final-head verdicts. Acquisition never reached any default/head fetch, anchor, B2 proof, integration or bundle. No precision/recall, natural-positive/control count, oracle eligibility or population-yield estimate exists. Zero graph-ready pairs represents missing acquisition.

Checkpoint (2) **incomplete material**: `~/.crosswire-evidence/s17b-r2/checkpoint-2.json`, SHA-256 `a502806e31f851fb52fa3b02537fa8ea9abaddd79ff87cd7ec5e7f13efb7c231`. Referenced files under `~/.crosswire-evidence/s17b-r2/checkpoint-2-material` include the untouched checkpoint (1), portable request claims/results/bodies, sanitized failure trace, recovered selections/rank/exclusion ledger, API-only object SHAs, recovery/preparation scripts, full existing apparatus/source hashes, frozen M3 and audited M2 adapter, runtime/stdlib/AST/native-library metadata, and oracle/detector environments. Object SHAs have **no Git object/tree/parent proof**; realized per-state scope is unavailable. The future measurement driver, virtual-state scope freeze and 5,400-second journal enforcement remain absent and require audit before any label. This is failure/evidence material, not a runnable measurement checkpoint.

The detector wheel was built and installed **offline from `git archive 30ff343`**, SHA-256 `54bd04dc861e029bf92ce40975b6b51ea2b994168f03d78aa2a2a8e5c800324e`; committed source, wheel and installed package bytes agree. The original S17 Pyright **1.1.407**, dependency tree, Python and Node bytes match their frozen hashes. Only interpreter/package metadata and file hashes were inspected: **zero checker/detector CLI invocations, version probes, diagnostics or labels**; no dependencies downloaded. The original environment remains unchanged. As previously disclosed, D-R2c followed one round-1 graph exclusion of unknown oracle status and applies uniformly; it was never reached in round 2.

D-Ev1 archive: `~/.crosswire-evidence/s17b-r2-acquisition-evidence.tgz`, SHA-256 `74928d29e6926d58d035ff6163f39fc0297b4b5ef2e3a9cf1a1bde14c283e9d5` (**518 file members, 2,598,412 bytes**). Every member/hash was verified; tar uid/gid/mtime are zero and uname/gname empty. Artifact paths are tokenized; committed source JSON and checkpoint (1) remain byte-identical. Runtime/oracle installations are hashed but not all duplicated; local copies remain available for audit. No expanded local paths or per-case evidence enter committed files. Release upload belongs to Polaris.

Aggregate: [s17b-r2-acquisition.json](s17b-r2-acquisition.json). **Stopped; no background job remains.** Vega audits the incomplete material; Polaris decides any future apparatus amendment or acquisition. No rerun or measurement is authorized by this report.
