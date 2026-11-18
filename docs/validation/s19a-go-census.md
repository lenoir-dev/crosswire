# S19a Go merge census — Deneb, 2026-11-18

**Completed; insufficient evidence to rank rules by frequency.** Of 334 selected two-parent merges, 331 integrate textually cleanly: 146 are oracle-eligible controls, 185 are unlabelled, and **zero** have green target/parents followed by a compiler-failing native integration. The other three have textual conflicts. This is a natural-history census, not detector evaluation; no precision/recall or release gate is claimed. No mutations or API scaffolds were substituted.

The complete per-case/state evidence is [s19a-go-census.json](s19a-go-census.json), SHA-256 `2d58544cf2fc54efedab8986cd104cf52a286b87a422f641270a33fc418ae4fd`. It contains repository URLs/SHAs, parents, merge bases, native/recorded trees, statuses, exclusions, raw build diagnostics, follow-up candidates, environment pins and downloaded-dependency hashes. Local directories are represented by portable tokens; no absolute local paths are published.

| Repository / domain | Pinned HEAD | Selected | Eligible controls | Unlabelled | Textual |
| --- | --- | ---: | ---: | ---: | ---: |
| [go-chi/chi](https://github.com/go-chi/chi) / HTTP routing | `c64ed7d6635f33a8b2feaff7dcfa55677023ac7d` | 61 | 0 | 61 | 0 |
| [spf13/pflag](https://github.com/spf13/pflag) / CLI parsing | `d77ebfaebd65f3d860d1351b6b4b01827e54e8e5` | 80 | 59 | 21 | 0 |
| [google/uuid](https://github.com/google/uuid) / identifiers | `2d3c2a9cc518326daf99a383f07c4d3c44317e4d` | 33 | 3 | 28 | 2 |
| [etcd-io/bbolt](https://github.com/etcd-io/bbolt) / embedded storage | `622eada16b5e733bc3bcacf17ca394452fc621f0` | 80 | 80 | 0 | 0 |
| [miekg/dns](https://github.com/miekg/dns) / DNS protocol | `b2d6c9f4480a71247e0df4ce709122852a2849cf` | 80 | 4 | 75 | 1 |

All five pinned current heads independently pass the same production build. That preflight does not make their historical parents eligible.

Selection was the latest 80 two-parent merges on each pinned first-parent history, or all available when fewer, without outcome-based case selection. [s19a-go-selection.json](s19a-go-selection.json) was written before repository builds for the initial four repositories. DNS was added after Chi's pre-module exclusions, within the five-repository limit; [its selection](s19a-go-dns-selection.json) was frozen before any DNS case build. This is an explicit sampling amendment, not a replacement of excluded cases. Selected merge dates span Chi 2015–2020, pflag 2016–2026, UUID 2015–2023, bbolt 2025–2026 and DNS 2015–2025: recent heads do not imply recent two-parent history.

The pinned oracle is **Go 1.27.1, darwin/arm64**, `GOFLAGS=-mod=readonly go build -gcflags=-e ./...`. `GOTOOLCHAIN=local`, `GOENV=off`, `GOWORK=off`, `CGO_ENABLED=0`, fixed GOOS/GOARCH, no custom tags, fixed isolated GOCACHE/GOMODCACHE and `GOMAXPROCS=2` apply identically to all states. The JSON pins Go/compiler/helper binaries, checker-code tables and apparatus sources. Builds run serially; timings are not performance observations. `_test.go`, ignored example directories, nested modules and inactive build-tag variants are outside this production oracle; vet/test execution is not claimed.

Network access was confined to public `git clone` and explicit `go mod download -json` setup. All 47 distinct module-file setup pairs completed successfully; 325 downloaded-cache artifacts are hashed. Original `go.mod`/`go.sum` bytes were restored after setup, before labels. Every build/list/checker run used `GOPROXY=off`, `GOSUMDB=off`, `GOVCS=*:off`; all 461 module-bearing states retained their module-file bytes. The fixed local module cache is required for offline replay, not a promise that downloads work offline.

For every clean merge, `git merge-tree --write-tree P1 P2` supplies the native integration; a deterministic unreferenced commit makes that tree buildable without moving refs. Both parents and the native result are replayed, and eligible cases additionally require a green unique merge-base target. All 331 native trees equal the recorded historical merge trees. Across the census and separate head preflight, 1,009 distinct commit states have build records: 460 pass; 549 remain unlabelled. Of the latter, 548 lack a root module and one pflag state needs module-file updates prohibited by the oracle. The 185 affected merges remain exclusions, never negative controls. Explicit offline builds confirmed every missing-module rejection after the initial preflight exclusions; no synthetic module files were invented.

Diagnostic categories use pinned `go/types` numeric codes, recovered from the version-pinned checker, and AST syntax spans joined to compiler file/line/column positions. English diagnostic text is retained for audit but never assigns a category. Missing first-party package candidates use package-loading evidence; cycles use import-graph strongly connected components. Unclassified/environment failures stay unlabelled. Four independent synthetic apparatus checks exercise GO-1/2/3/4/6/7/8/9, including column shifts within one call and result-count errors on the RHS; [s19a-category-smoke.json](s19a-category-smoke.json) is separate from the natural census. Python bookkeeping/category tests: **14 passed**. These checks validate the instrument, not natural rule prevalence.

| Candidate | Observed eligible compiler root causes | Frequency rank |
| --- | ---: | --- |
| GO-1 exported-name removal | 0 | tied; insufficient |
| GO-2 package removal | 0 | tied; insufficient |
| GO-3 arity change | 0 | tied; insufficient |
| GO-4 redeclaration | 0 | tied; insufficient |
| GO-5 constrained conjunctive removal | 0 | deferred by P1/P2; not ranked |
| GO-6 result-count / multi-assignment | 0 | tied; insufficient |
| GO-7 per-file imports | 0 | tied; insufficient |
| GO-8 import cycles | 0 | tied; insufficient |
| GO-9 same-package bare calls | 0 | tied; insufficient |

Follow-up audit inspected the next five first-parent commits after every selected merge: 91 distinct titles matched the declared fix/build/import screen, with candidate diffstats retained per case. Fourteen build/import-related patches were inspected more closely, with commit/path/hash/assessment recorded in `followup_patch_audit`. Examples: Chi's `c7a4192` changes an ignored example import path; `fc62510` only reorders imports; UUID's `ad90cc0` adds a README build badge; bbolt's `da9d57a` updates toolchain metadata. Other build-like titles include dependency and CI-action bumps. None establishes a new green-parent merge regression or attributable compiler repair. With no compiler-failing native integration, there is no positive follow-up build chain to classify; titles do not supply missing labels.

Sampling limits are material: 185/334 merges (55.39%) are unlabelled, and 191/331 clean integrations have one parent ancestral to the other, so both branches cannot introduce independent changes. Only 64 eligible controls have divergent parents; the other 82 eligible controls are ancestor-equivalent. Squash/rebase history, successful merges retained on main, and a fixed modern module toolchain all bias this cohort. `-gcflags=-e` does not eliminate dependent-package masking; a future multi-error incident still needs root-cause attribution and conservative exclusions. Zero observed failures does not show that Go semantic conflicts are rare or any rule unnecessary.

Recommendation to Polaris: keep GO-5 deferred and record that this census provides **no empirical ordering** among the other candidates. Before freezing a prevalence-driven supported set, choose a separate preregistered search over module-era divergent histories or independently reported broken integrations. Do not promote these controls or synthetic smoke cases into natural positives. This task leaves S16/S17/S18, runtime `src/**`, and both holdouts untouched; no project commit was made.

Reproduction apparatus: [s19a_census.py](../../benchmarks/s19a_census.py), [s19a_categories.go](../../benchmarks/s19a_categories.go), [s19a_followups.py](../../benchmarks/s19a_followups.py), [s19a_context_audit.py](../../benchmarks/s19a_context_audit.py). Clone the recorded URLs at their recorded SHAs under the designated census root, preserve the dependency snapshot, then run the primary census, DNS/follow-up extension and context audit in that order. Selection files refuse silent replacement; use a fresh evidence location for a new round. Apparatus labels are independent of crosswire; no detector was run.
