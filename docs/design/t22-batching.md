# T22 batching preparation — Altair

2026-11-18. Preparation only: source remains frozen pending Vega’s independent T21 acceptance. No T22/T23/T24 implementation or project commit was made.

Measured source: `d01d5e600e856c514da0667acfa5a76241deefbd`; source-file SHA-256 manifest remained stable. Git: `git version 2.50.1 (Apple Git-155)` (`/usr/bin/git`); Python: `3.11.17 (main, Oct  9 2026, 15:10:32) [Clang 22.1.3 ]`; platform: `macOS-27.2-arm64-arm-64bit`; CPU: Apple M5; RAM: 17,179,869,184 bytes.

## Fixture and method

- All synthetic repositories, scripts, raw CLI stdout, JSON measurements, `.prof` and top-25 text files are under `/tmp/altair-t22/`; this Markdown is my only authored workspace file. Repositories are local and have no remotes.
- `/tmp/altair-t22/repo`: 1,000 tracked files, 100 Python modules and 900 text assets. Target `T`; 30 selected branches; 435 unordered pairs. Each branch changes the return value of its own module-level function. No imports, API changes, semantic errors or textual conflicts; every measured CLI invocation exited 0 with empty stderr and complete coverage.
- `B00`…`B29` are single-commit siblings of T. `D00`…`D29` add an empty commit above the corresponding B tip: identical file changes, distinct direct parents. Both shapes live in one repository; only the named 30 heads are analysed in each cell. The second shape exposes the general merge-base path hidden by the existing sibling shortcut.
- Fresh interpreter per invocation, textual checks enabled, JSON output captured as bytes. Exact command families:

```sh
PYTHONDONTWRITEBYTECODE=1 <workspace>/.venv/bin/python -B -S -P -c <source-bootstrap> <workspace>/src check --repo /tmp/altair-t22/repo --format json B00 ... B29
PYTHONDONTWRITEBYTECODE=1 <workspace>/.venv/bin/python -B -S -P -c <source-bootstrap> <workspace>/src check --repo /tmp/altair-t22/repo --format json --target T --combined B00 ... B29
```

- Each of eight cells has five unprofiled wall samples. Within each shape, mode order alternates by repetition. Cold removes only this scratch repository’s `.git/crosswire/cache`; OS pages and Git objects are not flushed. Warm has untimed preparation with valid summaries. Every mode/shape retained identical stdout/stderr/exit across preparations and cold/warm samples.
- p50 = median; p95 = nearest rank, therefore the maximum of five. No censoring/errors. Wall time includes process startup/imports/teardown and excludes fixture hashing/cache preparation. Instrumentation and cProfile are separate extra runs, not the wall samples.
- Protected fixture HEAD/index/refs/config/worktree bytes and modes were checked outside timings; virtual unreferenced Git objects and Crosswire cache files are allowed. The profile worker disables bytecode writes. Source hashes were checked before/after both experiments.
- **Exploratory timings, not S14 acceptance:** Vega’s independent verification and other team work were active. Observed host load averages changed from 2.44/6.70/14.34 to 8.24/6.22/9.47 during preparation. Mode order reduces drift bias but cannot remove contention. Repeat on a quiet machine with the S14 interpreter/fixtures before judging budgets; the simple fixture says nothing about language semantics or conflict-heavy planning.

## Wall measurements

| Shape | Mode | Cache | Five samples, seconds | p50 s | p95 s |
| --- | --- | --- | --- | ---: | ---: |
| siblings | pairwise | cold | 8.612, 8.425, 8.342, 8.755, 8.345 | 8.425 | 8.755 |
| siblings | pairwise | warm | 7.376, 6.183, 6.148, 5.856, 5.905 | 6.148 | 7.376 |
| siblings | combined | cold | 3.517, 3.198, 3.389, 3.321, 3.242 | 3.321 | 3.517 |
| siblings | combined | warm | 2.471, 2.071, 1.968, 2.154, 2.056 | 2.071 | 2.471 |
| depth2 | pairwise | cold | 11.885, 17.361, 17.745, 21.460, 21.172 | 17.745 | 21.460 |
| depth2 | pairwise | warm | 14.289, 14.585, 15.922, 16.386, 15.386 | 15.386 | 16.386 |
| depth2 | combined | cold | 2.667, 3.097, 4.107, 4.908, 4.794 | 4.107 | 4.908 |
| depth2 | combined | warm | 2.465, 3.699, 3.334, 3.219, 2.958 | 3.219 | 3.699 |

Warm p95 pairwise/combined ratios are **2.99×** for siblings and **4.43×** for depth-two heads: both exceed the proposed ≤2× target here. These runs use plain pairwise `check`; adding `--target T` to pairwise would add 30 target merge-base resolutions on these fixtures. It would not remove the 435 pair merges or the depth-two pair-base queries.

## Git subprocesses and time attribution

Counts below are direct Python→Git process launches in one separately profiled run per cell. The persistent `cat-file` process counts once, not once per object request. Git-internal helper children are not counted. “Version” means `git --version`.

| Shape | Mode/cache | Total | merge-tree | merge-base | cat-file | diff | ls-tree | rev-parse | rev-list | commit-tree | Version |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| siblings | pairwise/cold | 564 | 435 | 0 | 1 | 30 | 62 | 34 | 1 | 0 | 1 |
| siblings | combined/cold | 222 | 30 | 30 | 1 | 31 | 63 | 35 | 1 | 30 | 1 |
| siblings | pairwise/warm | 503 | 435 | 0 | 1 | 0 | 31 | 34 | 1 | 0 | 1 |
| siblings | combined/warm | 162 | 30 | 30 | 1 | 1 | 33 | 35 | 1 | 30 | 1 |
| depth2 | pairwise/cold | 999 | 435 | 435 | 1 | 30 | 62 | 34 | 1 | 0 | 1 |
| depth2 | combined/cold | 222 | 30 | 30 | 1 | 31 | 63 | 35 | 1 | 30 | 1 |
| depth2 | pairwise/warm | 938 | 435 | 435 | 1 | 0 | 31 | 34 | 1 | 0 | 1 |
| depth2 | combined/warm | 162 | 30 | 30 | 1 | 1 | 33 | 35 | 1 | 30 | 1 |

- Sibling warm pairwise: `merge_tree_conflicts()` has 6.930 s cumulative of 8.036 s profiled main time (86.2%); synchronous `merge-tree` subprocess calls total 6.829 s. There are **zero** scalar merge-base calls: `engine.analyze()` already uses one `direct_parents()` rev-list pass for siblings.
- Depth-two warm pairwise: `merge_tree_conflicts()` 7.048 s + `merge_base()` 6.908 s of 15.304 s (91.2%). Synchronous merge-tree/merge-base waits are 6.947/6.809 s. These are two independent O(pairs) native-launch bottlenecks.
- Warm combined has 30 dependent merge-tree steps and 30 commit-tree steps; its final commit feeds the next step. The corresponding sibling integration frame is 0.741 s of 1.968 s. Those steps cannot be sent together as independent pair requests.
- Warm pairwise still has 34 revision-resolution/discovery calls and 31 ls-tree calls; cold additionally runs 30 diff calls and 31 more tree listings. These become secondary after pair batching. The existing cat-file stream is already amortised.
- cProfile’s `poll`/`communicate` frames measure waiting for children, IPC and scheduling, not Git CPU time. Cumulative rows overlap and must not be added as independent costs. The `t22_probe.py` rows are measurement wrappers. Top 25 cumulative frames for every cell appear in the appendix.

## Native batching experiments (five runs each)

These execute Git commands outside Crosswire; no production runtime was patched. They are component measurements, not an optimized CLI benchmark. All 435 tree IDs and conflicted-path records were checked against serial results in each shape/repetition. Native merge objects were already warm.

| Operation | Shape | Git launches | p50 s | p95 s |
| --- | --- | ---: | ---: | ---: |
| merge-tree serial_435 | siblings | 435 | 5.373 | 7.120 |
| merge-tree batch_1 | siblings | 1 | 0.071 | 0.074 |
| merge-tree chunks_2 | siblings | 2 | 0.082 | 0.086 |
| merge-tree serial_435 | depth2 | 435 | 4.780 | 4.867 |
| merge-tree batch_1 | depth2 | 1 | 0.073 | 0.077 |
| merge-tree chunks_2 | depth2 | 2 | 0.087 | 0.089 |
| merge-base all_per_pair_435 | depth2 | 435 | 7.772 | 12.687 |
| merge-base rev_list_graph_1 | depth2 | 1 | 0.034 | 0.040 |

The graph experiment reads 61 commits once using `rev-list --topo-order --parents <30 full SHAs>`, derives ancestor sets, and computes each pair’s unique best common ancestor. All 435 results equal `merge-base --all` on this fixture. This small set-based prototype is not a general production graph implementation; deep/large histories and ambiguous bases require the rules below.

An existing CLI diagnostic, `--no-textual`, gave the following warm timings (five runs each). Its stdout happened to equal ordinary pairwise output on these clean fixtures. It isolates the remaining work; disabling textual checks is not the proposed optimization.

| Shape | p50 s | p95 s |
| --- | ---: | ---: |
| siblings | 1.978 | 2.084 |
| depth2 | 13.826 | 14.342 |

**Expected gain, inference:** reducing 435 pair-merge launches to two removes the dominant sibling cost; eliminating 435 unique-base launches is additionally necessary for the depth-two shape. The profiled residual is about 1.1–1.4 s before new batch/graph parsing, startup and capability checks. Budget conservatively for **2–4× warm sibling** and **4–8× warm depth-two** improvement, rather than transferring the native 50–90× ratio to the whole CLI. A roughly 1.5–3 s warm CLI is a plausible hypothesis on these fixtures, not a measured optimized result or a p95 guarantee. Re-measure end-to-end after acceptance, including 5/10/30 branches and existing S14 cells.

## Capabilities and minimum versions

Historical bounds come from upstream tagged source/manuals and release notes; live probes use Apple Git 2.50.1. No older Git was installed or executed. “≤” for ancient facilities is a documentation bound, not a claim about the exact first release.

| Facility | Upstream minimum / verified historical bound | Live result / use |
| --- | --- | --- |
| merge-tree `--write-tree --name-only -z --no-messages` | 2.38 ([release notes](https://raw.githubusercontent.com/git/git/v2.38.0/Documentation/RelNotes/2.38.0.txt), [tagged manual](https://raw.githubusercontent.com/git/git/v2.38.0/Documentation/git-merge-tree.txt)) | Works; existing serial backend and 2.38 fallback. |
| merge-tree `--stdin` with two SHAs/line | **2.39**, not 2.40 ([release notes](https://raw.githubusercontent.com/git/git/v2.39.0/Documentation/RelNotes/2.39.0.txt), [option implementation](https://raw.githubusercontent.com/git/git/v2.39.0/builtin/merge-tree.c)) | Mixed clean/conflict requests, duplicate and reversed pairs worked with the full flag bundle. |
| merge-tree `--merge-base`, or base-prefixed stdin records | 2.40 ([release notes](https://raw.githubusercontent.com/git/git/v2.40.0/Documentation/RelNotes/2.40.0.txt), [parser](https://raw.githubusercontent.com/git/git/v2.40.0/builtin/merge-tree.c)) | Not needed for T22: let Git preserve recursive/virtual-base semantics. |
| cat-file `--batch` / `--batch-check` | 1.5.6 ([tagged manual](https://raw.githubusercontent.com/git/git/v1.5.6/Documentation/git-cat-file.txt); absent in [1.5.5](https://raw.githubusercontent.com/git/git/v1.5.5/Documentation/git-cat-file.txt)) | Both worked; no new minimum for Crosswire. |
| cat-file `--buffer` | 2.6 ([tagged manual](https://raw.githubusercontent.com/git/git/v2.6.0/Documentation/git-cat-file.txt)) | Buffered command probe worked with explicit flush; defer changing the existing stream. |
| cat-file `--batch-command` | 2.36 ([release notes](https://raw.githubusercontent.com/git/git/v2.36.0/Documentation/RelNotes/2.36.0.txt)) | `info`/`contents` worked; current core already uses it. |
| cat-file lowercase `-z` | 2.38 ([release notes](https://raw.githubusercontent.com/git/git/v2.38.0/Documentation/RelNotes/2.38.0.txt)) | NUL input with newline headers works; current reader uses this. |
| cat-file uppercase `-Z` | 2.42 ([release notes](https://raw.githubusercontent.com/git/git/v2.42.0/Documentation/RelNotes/2.42.0.txt)) | NUL input **and output** works; requires a different header reader, unavailable at 2.38. |
| merge-base `--all` per pair | ≤1.5.0 ([tagged manual](https://raw.githubusercontent.com/git/git/v1.5.0/Documentation/git-merge-base.txt)) | Works, but is still 435 launches; not a multi-pair protocol. |
| rev-list `--parents --topo-order` | ≤1.0.0 ([tagged manual](https://raw.githubusercontent.com/git/git/v1.0.0/Documentation/git-rev-list.txt)) | One walk returns all 61 reachable commits; available at the 2.38 floor. |
| show-branch `--merge-base` | ≤1.0.0 ([tagged manual](https://raw.githubusercontent.com/git/git/v1.0.0/Documentation/git-show-branch.txt)) | At 30 heads this binary ignores the last four, warns “cannot handle more than 26 refs”, and exits 0. Also answers an N-head question, not all pair questions. Do not use. |

### Framing and negative controls

- With `--stdin --name-only -z --no-messages`, records have `status NUL tree NUL [path NUL …] NUL`. Status **1 means clean; 0 means conflict**, the opposite sense of standalone conflict exit codes. Clean and conflicted records together produce process exit 0. Parse records and cardinality, not just process status or a nonempty path list.
- The live five-request probe (clean, conflict, clean, reversed conflict, repeated conflict) exactly matched standalone tree/path results. A conflicted filename containing both LF and TAB survived unchanged. Save filesystem bytes and use the current `os.fsdecode` and sorted-set path policy; never split paths on lines.
- An invalid middle SHA on this Apple build returned **exit 1**, only the first completed record, and stderr `merge-tree: 000…000 - not something we can merge`. The trailing valid request never ran. Thus even exit 1 can mean batch failure; incomplete output cannot be interpreted as clean or partially safe. Raw bytes are in `capabilities.json`.
- A synthetic criss-cross has two best bases. `merge-base <tip1> <tip2>` selected `47af866b…`, while reversing the tips selected `e818e99d…`. Sorting/normalizing the pair or selecting the lexicographically first `--all` result changes existing behavior. An unrelated-root pair returned exit 1 with no base.

## Proposed implementation sequence after acceptance

1. **Batch only independent pairwise text merges first.** Keep `engine.analyze()`’s ordered pair loop, base calculations, adapter summaries, warnings, prefilter and reporters. Add a private run-scoped merge-result provider in `git.py`; send resolved full SHAs in the original pair orientation to `merge-tree --stdin --write-tree --name-only -z --no-messages`. Use bounded chunks (proposal: 256 pairs, hence two chunks for 435 pairs). Keep tree IDs/path bytes and per-record status separate; expose exactly the existing `merge_tree_conflicts()` result.
2. **Detect the complete capability, not a version string alone.** After existing repository/version validation, perform a silent two-record self-merge probe with a known resolved commit and the exact flag bundle; validate statuses, OIDs, record count and EOF. Cache support per executable/version for the run. Backported/vendor Git may differ. Unsupported or inconclusive probes choose the existing serial path. Git 2.38 remains supported; do not add notices, report fields or change the advertised floor.
3. **Preserve evaluation and error order.** Resolve user refs and validate inputs as today. Treat speculative batch failures as internal pending results; at the original logical pair position, run the existing serial call to recover its exact error behavior. On malformed/truncated output, unexpected stderr, wrong record count, or fatal process status, discard that chunk and replay it lazily in original order. Do not expose speculative stderr or report errors before the summaries/parse warnings that historically precede that pair. Avoid partial trusted results from a failed chunk. Custom merge drivers/configuration need explicit parity tests; retain serial fallback when equivalence cannot be established.
4. **Then remove repeated unique-base queries.** Retain the sibling `direct_parents()` shortcut. For unresolved pairs, use one bounded rev-list parent graph and an iterative traversal/bitset or memoized ancestry index. A best common ancestor has no common descendant; use the result only when the relevant ancestry is complete and the best base is unique. Preserve pair orientation. Multiple bases, missing parents, graph-size/time bounds or unsupported topology/configuration fall back to the existing ordered `git.merge_base()` query. A graph bound is an invisible optimization fallback, not a new coverage limitation. Do not replace scalar selection with sorted `--all`, `--octopus`, or the common base of all 30 heads. Large histories can make a whole graph walk slower; predeclare node/byte bounds and never claim uniqueness from a truncated graph.
5. **Keep dependent integration and secondary batching separate.** Do not pipeline `integrate._merge()`’s next unknown virtual commit, alter commit-tree parent order/message/environment, replace N-way analysis with pair unions, or skip text checks using the semantic prefilter. Revision-resolution batching (34/35 calls), cold diff batching (30 calls), and coverage ls-tree batching (31/33 warm calls) are later candidates only if the main target is still missed. Keep cat-file’s one existing bounded stream and 2 MB/binary/UTF-8 protections.
6. **Prove parity before optimizing further.** Replay Deneb’s immutable 334-fixture / 43,726-record-per-side gate and Vega’s independent comparison on the T22 source fingerprint. Exercise native batch and forced serial fallback, and use actual Git 2.38 in compatibility checks. Cover mixed results, error precedence, malformed/partial streams, duplicate pairs, permutations, odd byte filenames, binary/deletion/rename/directory conflicts, SHA-256, multiple merge bases, unrelated/shallow/bare/linked repositories, hooks/configuration and read-only state. Goldens are not refreshed for T22.

**Compatibility/performance boundary:** serial merge-tree fallback preserves 2.38 correctness but cannot promise the capable-host batch speedup. The graph optimization still helps distinct-parent histories there. Acceptance should measure the ≤2× p95 target on the declared capable Git 2.50.1/M5 setup and separately verify 2.38 bytes; if the same speed target is required on 2.38, that needs an explicit additional design (e.g. bounded independent workers with preserved diagnostics order), not an unmeasured claim.

## T23 and T24 preparation

### Final4 review decisions (Polaris, 2026-11-18)

Vega's [code review](../reviews/v0.5-t22-code-vega.md) accepted the unique-base
proof and ordered fallback, subject to additional evidence and resource guards.
The final4 implementation and validation follow these decisions:

- Capability detection creates a disposable bare repository outside the user's
  repository. A deterministic three-commit history provides one clean pair and
  one conflicted pair. The complete batch records, including tree IDs, status and
  paths, must equal both scalar results. Repository redirection and user Git
  configuration are removed from the scratch environment. The user's effective
  configuration is checked separately for external drivers, filters and promisor
  fetches; those cases retain serial execution. Probe results live for one run.
- The first speculative chunk contains at most **16 pairs**, subsequent chunks
  at most **256**. A failed chunk disables batching for the rest of the run;
  discarded results are replayed only at the original serial evaluation point.
  Speculative merges may create **unreachable Git objects for later pairs** even
  if analysis exits early. These objects are prunable; HEAD, index, refs, config,
  logs and working-tree bytes/modes remain protected. The smaller first chunk
  bounds this side effect for early failures but does not eliminate it.
- Each batch has a **64 MiB stdout cap**. Capture drains input/output without
  holding an unbounded response, kills and reaps an over-cap process, discards
  the entire chunk and selects serial replay. Unexpected stderr does the same.
- When available, commit-graph fanout metadata provides a cheap commit count.
  A count above 20,000 skips the ancestry attempt, including split graphs. This
  is conservative: a graph covering more than the selected tips need disables
  only an optimization. Missing, unreadable or inconclusive metadata does not
  establish a count. Without usable metadata, a large history can still pay up
  to the one-second capture deadline plus bounded parsing/construction overhead
  before scalar fallback. The capture remains capped at 4 MiB/20,000 nodes and
  construction at one second. Measurements include a history above the bound,
  with and without a commit graph.
- `git.pair_merges()` and `git.pair_bases()` are the engine-facing factories;
  the unused version argument is removed. Git 2.38 capability fallback remains
  behavior-based. Its acceptance policy is **byte parity only**, without a speed
  promise.
- `tests/test_t22_batching.py` adds deterministic native-Git oracles, executable
  fault shims, chunk-boundary/fallback controls, all ancestry bounds, metadata
  guards, SHA-256 and child/pipe cleanup checks. Small 4–5-branch measurements
  include the scratch probe and ancestry guard subprocesses, not just merges in
  the user's repository. All original S14 budgets remain binding.

**T23 — run-wide trials.** Give `AnalysisRun` a single trial executor/statistics object shared by combined culprit search, repaired-by-third search and planner states. Freeze the unit before adding fields: recommend one candidate integrated-state evaluation, with actual new integrations and whole-state cache hits counted separately; distinguish partial prefix reuse in `integrate._memo` from a fully cached trial. Count a request once at that boundary, not once in both planner and combined; do not infer totals from cache sizes or empty bound flags. Start with `limit: null` unless a run-wide budget is actually enforced before work. If a budget is enforced, unchecked work must retain bounded coverage and honest culprit exactness. T23 is deliberately additive: update offline schemas and have Deneb refresh the authorized goldens after T22 parity, not during this freeze.

**T24 — blocked-plan RSS.** Keep every accepted S14 per-cell p95/RSS budget on its original fixture/interpreter, and establish a separate, predeclared blocked-fixture baseline before changing caches. Add (a) 21 safe branches, including seven disjoint edits to one shared file, followed by eight independently API-breaking branches and one conflicting edit to that shared file: nine blocked branches exercise the remaining-branch shortcut, while seven same-path candidate culprits exercise the candidate cap; and (b) 22 safe branches followed by eight independently API-breaking branches: eight remaining enables the existing size-2/3 group search (28+56 groups) instead of bypassing it at >8. Include many first-party target references and distinct source blobs so `AnalysisRun.indexes`, adapter module/parse caches and planner `states` actually accumulate. Leave search limits unchanged and assert findings, coverage hits and read-only state.

Record cold/warm wall time and peak **worker** RSS in fresh processes (Darwin ru_maxrss is bytes; Linux is KiB). Concurrent Git-tree peak is a different metric; neither sum of child maxima nor RUSAGE_CHILDREN’s largest child is a simultaneous process-tree peak. Use allocation snapshots and retained index/state/blob counts to locate Python growth; compare deterministic per-run cleanup or compact bounded data only after measurement, without restoring the previous 8,192-entry eviction/thrashing failure or losing consulted-file coverage on cache hits. This round does not produce a T24 budget or memory result.

## Reproduction and artifacts

```sh
PYTHONDONTWRITEBYTECODE=1 <workspace>/.venv/bin/python -B /tmp/altair-t22/t22_probe.py
PYTHONDONTWRITEBYTECODE=1 <workspace>/.venv/bin/python -B /tmp/altair-t22/capabilities.py
PYTHONDONTWRITEBYTECODE=1 <workspace>/.venv/bin/python -B /tmp/altair-t22/native_micro.py
```

`fixture.json` fixes the target/tip IDs and workload; `measurements.json` contains all 40 wall samples, environment and source hashes; `*-profile.json/.prof/.txt` hold launch counts, synchronous Git timing and cProfile; `native-micro.json` contains five-run component experiments; `capabilities.json` holds raw protocol probes, malformed-input behavior and DAG controls. These local `/tmp` artifacts are ephemeral, not a portable published benchmark corpus. This document preserves all primary wall samples, command counts and top-25 frames. Reruns overwrite scratch measurement outputs, not source or the immutable T21 baseline.

## Appendix: cProfile top 25 cumulative frames

One extra profiled run per cell; import/startup/atexit cost lies outside the profiler. Counts and times belong to that run and can differ from the unprofiled five-run quantiles. Times are seconds; cumulative rows overlap.

<details><summary>siblings — pairwise — cold (7.541 s profiled)</summary>

| Calls | Self s | Cumulative s | Function |
| ---: | ---: | ---: | --- |
| 1 | 0.000 | 7.541 | `src/crosswire/cli.py:99 main` |
| 1 | 0.000 | 7.541 | `src/crosswire/cli.py:17 _main` |
| 1 | 0.009 | 7.534 | `src/crosswire/engine.py:181 analyze` |
| 563 | 0.005 | 7.369 | `src/crosswire/git.py:30 _run` |
| 563 | 0.019 | 7.288 | `t22_probe.py:80 run` |
| 563 | 0.016 | 7.249 | `subprocess.py:506 run` |
| 563 | 0.004 | 6.268 | `subprocess.py:1165 communicate` |
| 563 | 0.030 | 6.264 | `subprocess.py:2062 _communicate` |
| 1247 | 0.008 | 6.188 | `selectors.py:402 select` |
| 1247 | 6.179 | 6.179 | `~:0 <method 'poll' of 'select.poll' objects>` |
| 435 | 0.011 | 5.847 | `src/crosswire/git.py:317 merge_tree_conflicts` |
| 564 | 0.013 | 0.963 | `t22_probe.py:77 __init__` |
| 564 | 0.037 | 0.945 | `subprocess.py:807 __init__` |
| 564 | 0.074 | 0.889 | `subprocess.py:1791 _execute_child` |
| 870 | 0.005 | 0.815 | `src/crosswire/engine.py:221 get_summary` |
| 30 | 0.001 | 0.780 | `src/crosswire/engine.py:161 side` |
| 1 | 0.002 | 0.433 | `src/crosswire/coverage.py:9 inspect` |
| 60 | 0.000 | 0.433 | `src/crosswire/engine.py:170 <genexpr>` |
| 30 | 0.000 | 0.433 | `src/crosswire/lang/python/adapter.py:268 summarize` |
| 30 | 0.001 | 0.433 | `src/crosswire/lang/python/adapter.py:378 _legacy_summary` |
| 60 | 0.001 | 0.430 | `src/crosswire/lang/python/adapter.py:321 parse` |
| 30 | 0.001 | 0.425 | `src/crosswire/git.py:272 entries_for_paths` |
| 60 | 0.000 | 0.417 | `src/crosswire/lang/base.py:145 read` |
| 60 | 0.001 | 0.417 | `src/crosswire/git.py:285 read_file` |
| 564 | 0.413 | 0.414 | `~:0 <built-in method _posixsubprocess.fork_exec>` |

</details>

<details><summary>siblings — combined — cold (2.884 s profiled)</summary>

| Calls | Self s | Cumulative s | Function |
| ---: | ---: | ---: | --- |
| 1 | 0.000 | 2.884 | `src/crosswire/cli.py:99 main` |
| 1 | 0.000 | 2.884 | `src/crosswire/cli.py:17 _main` |
| 1 | 0.000 | 2.882 | `src/crosswire/combined.py:172 analyze_combined` |
| 221 | 0.008 | 2.712 | `t22_probe.py:80 run` |
| 221 | 0.006 | 2.696 | `subprocess.py:506 run` |
| 221 | 0.001 | 2.326 | `subprocess.py:1165 communicate` |
| 221 | 0.013 | 2.325 | `subprocess.py:2062 _communicate` |
| 595 | 0.003 | 2.292 | `selectors.py:402 select` |
| 595 | 2.289 | 2.289 | `~:0 <method 'poll' of 'select.poll' objects>` |
| 161 | 0.001 | 1.981 | `src/crosswire/git.py:30 _run` |
| 1 | 0.001 | 1.721 | `src/crosswire/combined.py:91 __init__` |
| 30 | 0.001 | 0.807 | `src/crosswire/engine.py:161 side` |
| 1 | 0.000 | 0.766 | `src/crosswire/integrate.py:63 integrate` |
| 30 | 0.001 | 0.766 | `src/crosswire/integrate.py:41 _merge` |
| 60 | 0.001 | 0.761 | `src/crosswire/integrate.py:25 _run` |
| 60 | 0.000 | 0.448 | `src/crosswire/engine.py:170 <genexpr>` |
| 30 | 0.000 | 0.448 | `src/crosswire/lang/python/adapter.py:268 summarize` |
| 30 | 0.001 | 0.447 | `src/crosswire/lang/python/adapter.py:378 _legacy_summary` |
| 60 | 0.001 | 0.445 | `src/crosswire/lang/python/adapter.py:321 parse` |
| 31 | 0.000 | 0.440 | `src/crosswire/git.py:75 resolve` |
| 160 | 0.000 | 0.431 | `src/crosswire/lang/base.py:145 read` |
| 160 | 0.001 | 0.431 | `src/crosswire/git.py:285 read_file` |
| 1 | 0.000 | 0.426 | `src/crosswire/combined.py:97 <listcomp>` |
| 31 | 0.016 | 0.410 | `src/crosswire/git.py:218 tree_entries` |
| 1 | 0.002 | 0.369 | `src/crosswire/coverage.py:9 inspect` |

</details>

<details><summary>siblings — pairwise — warm (8.036 s profiled)</summary>

| Calls | Self s | Cumulative s | Function |
| ---: | ---: | ---: | --- |
| 1 | 0.000 | 8.036 | `src/crosswire/cli.py:99 main` |
| 1 | 0.000 | 8.036 | `src/crosswire/cli.py:17 _main` |
| 1 | 0.009 | 8.030 | `src/crosswire/engine.py:181 analyze` |
| 502 | 0.005 | 7.944 | `src/crosswire/git.py:30 _run` |
| 502 | 0.029 | 7.858 | `t22_probe.py:80 run` |
| 502 | 0.017 | 7.808 | `subprocess.py:506 run` |
| 435 | 0.007 | 6.930 | `src/crosswire/git.py:317 merge_tree_conflicts` |
| 502 | 0.004 | 6.814 | `subprocess.py:1165 communicate` |
| 502 | 0.028 | 6.809 | `subprocess.py:2062 _communicate` |
| 1005 | 0.009 | 6.731 | `selectors.py:402 select` |
| 1005 | 6.720 | 6.720 | `~:0 <method 'poll' of 'select.poll' objects>` |
| 503 | 0.017 | 0.975 | `t22_probe.py:77 __init__` |
| 503 | 0.033 | 0.953 | `subprocess.py:807 __init__` |
| 503 | 0.073 | 0.899 | `subprocess.py:1791 _execute_child` |
| 1 | 0.000 | 0.549 | `src/crosswire/engine.py:187 <listcomp>` |
| 30 | 0.000 | 0.549 | `src/crosswire/git.py:75 resolve` |
| 1 | 0.001 | 0.365 | `src/crosswire/coverage.py:9 inspect` |
| 503 | 0.358 | 0.358 | `~:0 <built-in method _posixsubprocess.fork_exec>` |
| 30 | 0.000 | 0.338 | `src/crosswire/git.py:272 entries_for_paths` |
| 2009 | 0.307 | 0.307 | `~:0 <built-in method posix.read>` |
| 503 | 0.013 | 0.080 | `<frozen os>:713 copy` |
| 503 | 0.031 | 0.074 | `subprocess.py:1282 _close_pipe_fds` |
| 85037 | 0.030 | 0.046 | `<frozen os>:806 fsencode` |
| 36787 | 0.019 | 0.043 | `<frozen os>:674 __getitem__` |
| 870 | 0.001 | 0.040 | `src/crosswire/engine.py:221 get_summary` |

</details>

<details><summary>siblings — combined — warm (1.968 s profiled)</summary>

| Calls | Self s | Cumulative s | Function |
| ---: | ---: | ---: | --- |
| 1 | 0.000 | 1.968 | `src/crosswire/cli.py:99 main` |
| 1 | 0.000 | 1.968 | `src/crosswire/cli.py:17 _main` |
| 1 | 0.000 | 1.967 | `src/crosswire/combined.py:172 analyze_combined` |
| 161 | 0.005 | 1.878 | `t22_probe.py:80 run` |
| 161 | 0.004 | 1.868 | `subprocess.py:506 run` |
| 161 | 0.001 | 1.617 | `subprocess.py:1165 communicate` |
| 161 | 0.009 | 1.616 | `subprocess.py:2062 _communicate` |
| 356 | 0.002 | 1.594 | `selectors.py:402 select` |
| 356 | 1.592 | 1.592 | `~:0 <method 'poll' of 'select.poll' objects>` |
| 101 | 0.001 | 1.162 | `src/crosswire/git.py:30 _run` |
| 1 | 0.000 | 0.786 | `src/crosswire/combined.py:91 __init__` |
| 1 | 0.000 | 0.741 | `src/crosswire/integrate.py:63 integrate` |
| 30 | 0.001 | 0.741 | `src/crosswire/integrate.py:41 _merge` |
| 60 | 0.000 | 0.737 | `src/crosswire/integrate.py:25 _run` |
| 1 | 0.001 | 0.388 | `src/crosswire/coverage.py:9 inspect` |
| 32 | 0.001 | 0.374 | `src/crosswire/git.py:272 entries_for_paths` |
| 31 | 0.000 | 0.347 | `src/crosswire/git.py:75 resolve` |
| 30 | 0.000 | 0.342 | `src/crosswire/git.py:93 merge_base` |
| 30 | 0.000 | 0.342 | `src/crosswire/git.py:87 _merge_base_sha` |
| 1 | 0.000 | 0.336 | `src/crosswire/combined.py:97 <listcomp>` |
| 162 | 0.003 | 0.247 | `t22_probe.py:77 __init__` |
| 162 | 0.008 | 0.242 | `subprocess.py:807 __init__` |
| 162 | 0.017 | 0.229 | `subprocess.py:1791 _execute_child` |
| 162 | 0.103 | 0.103 | `~:0 <built-in method _posixsubprocess.fork_exec>` |
| 649 | 0.069 | 0.069 | `~:0 <built-in method posix.read>` |

</details>

<details><summary>depth2 — pairwise — cold (18.625 s profiled)</summary>

| Calls | Self s | Cumulative s | Function |
| ---: | ---: | ---: | --- |
| 1 | 0.000 | 18.625 | `src/crosswire/cli.py:99 main` |
| 1 | 0.000 | 18.625 | `src/crosswire/cli.py:17 _main` |
| 1 | 0.021 | 18.617 | `src/crosswire/engine.py:181 analyze` |
| 998 | 0.012 | 18.334 | `src/crosswire/git.py:30 _run` |
| 998 | 0.047 | 18.129 | `t22_probe.py:80 run` |
| 998 | 0.039 | 18.032 | `subprocess.py:506 run` |
| 998 | 0.009 | 15.640 | `subprocess.py:1165 communicate` |
| 998 | 0.076 | 15.630 | `subprocess.py:2062 _communicate` |
| 2113 | 0.033 | 15.434 | `selectors.py:402 select` |
| 2113 | 15.397 | 15.397 | `~:0 <method 'poll' of 'select.poll' objects>` |
| 435 | 0.029 | 8.129 | `src/crosswire/git.py:317 merge_tree_conflicts` |
| 435 | 0.006 | 7.947 | `src/crosswire/git.py:93 merge_base` |
| 435 | 0.010 | 7.938 | `src/crosswire/git.py:87 _merge_base_sha` |
| 999 | 0.032 | 2.348 | `t22_probe.py:77 __init__` |
| 999 | 0.099 | 2.303 | `subprocess.py:807 __init__` |
| 999 | 0.172 | 2.152 | `subprocess.py:1791 _execute_child` |
| 870 | 0.009 | 1.317 | `src/crosswire/engine.py:221 get_summary` |
| 30 | 0.001 | 1.262 | `src/crosswire/engine.py:161 side` |
| 999 | 0.853 | 0.854 | `~:0 <built-in method _posixsubprocess.fork_exec>` |
| 4110 | 0.755 | 0.755 | `~:0 <built-in method posix.read>` |
| 60 | 0.000 | 0.698 | `src/crosswire/engine.py:170 <genexpr>` |
| 30 | 0.000 | 0.698 | `src/crosswire/lang/python/adapter.py:268 summarize` |
| 30 | 0.001 | 0.697 | `src/crosswire/lang/python/adapter.py:378 _legacy_summary` |
| 60 | 0.002 | 0.693 | `src/crosswire/lang/python/adapter.py:321 parse` |
| 60 | 0.000 | 0.672 | `src/crosswire/lang/base.py:145 read` |

</details>

<details><summary>depth2 — combined — cold (4.582 s profiled)</summary>

| Calls | Self s | Cumulative s | Function |
| ---: | ---: | ---: | --- |
| 1 | 0.000 | 4.582 | `src/crosswire/cli.py:99 main` |
| 1 | 0.000 | 4.582 | `src/crosswire/cli.py:17 _main` |
| 1 | 0.001 | 4.580 | `src/crosswire/combined.py:172 analyze_combined` |
| 221 | 0.012 | 4.312 | `t22_probe.py:80 run` |
| 221 | 0.009 | 4.290 | `subprocess.py:506 run` |
| 221 | 0.002 | 3.732 | `subprocess.py:1165 communicate` |
| 221 | 0.018 | 3.730 | `subprocess.py:2062 _communicate` |
| 585 | 0.006 | 3.681 | `selectors.py:402 select` |
| 585 | 3.675 | 3.675 | `~:0 <method 'poll' of 'select.poll' objects>` |
| 161 | 0.002 | 3.120 | `src/crosswire/git.py:30 _run` |
| 1 | 0.001 | 2.667 | `src/crosswire/combined.py:91 __init__` |
| 30 | 0.001 | 1.303 | `src/crosswire/engine.py:161 side` |
| 1 | 0.001 | 1.248 | `src/crosswire/integrate.py:63 integrate` |
| 30 | 0.002 | 1.247 | `src/crosswire/integrate.py:41 _merge` |
| 60 | 0.001 | 1.240 | `src/crosswire/integrate.py:25 _run` |
| 60 | 0.000 | 0.723 | `src/crosswire/engine.py:170 <genexpr>` |
| 30 | 0.000 | 0.723 | `src/crosswire/lang/python/adapter.py:268 summarize` |
| 30 | 0.001 | 0.722 | `src/crosswire/lang/python/adapter.py:378 _legacy_summary` |
| 60 | 0.002 | 0.717 | `src/crosswire/lang/python/adapter.py:321 parse` |
| 160 | 0.000 | 0.696 | `src/crosswire/lang/base.py:145 read` |
| 160 | 0.001 | 0.696 | `src/crosswire/git.py:285 read_file` |
| 31 | 0.026 | 0.662 | `src/crosswire/git.py:218 tree_entries` |
| 1 | 0.003 | 0.626 | `src/crosswire/coverage.py:9 inspect` |
| 32 | 0.001 | 0.615 | `src/crosswire/git.py:272 entries_for_paths` |
| 31 | 0.000 | 0.608 | `src/crosswire/git.py:75 resolve` |

</details>

<details><summary>depth2 — pairwise — warm (15.304 s profiled)</summary>

| Calls | Self s | Cumulative s | Function |
| ---: | ---: | ---: | --- |
| 1 | 0.000 | 15.304 | `src/crosswire/cli.py:99 main` |
| 1 | 0.000 | 15.304 | `src/crosswire/cli.py:17 _main` |
| 1 | 0.014 | 15.296 | `src/crosswire/engine.py:181 analyze` |
| 937 | 0.010 | 15.152 | `src/crosswire/git.py:30 _run` |
| 937 | 0.036 | 14.990 | `t22_probe.py:80 run` |
| 937 | 0.033 | 14.916 | `subprocess.py:506 run` |
| 937 | 0.010 | 13.026 | `subprocess.py:1165 communicate` |
| 937 | 0.074 | 13.014 | `subprocess.py:2062 _communicate` |
| 1875 | 0.019 | 12.844 | `selectors.py:402 select` |
| 1875 | 12.822 | 12.822 | `~:0 <method 'poll' of 'select.poll' objects>` |
| 435 | 0.009 | 7.048 | `src/crosswire/git.py:317 merge_tree_conflicts` |
| 435 | 0.006 | 6.908 | `src/crosswire/git.py:93 merge_base` |
| 435 | 0.005 | 6.899 | `src/crosswire/git.py:87 _merge_base_sha` |
| 938 | 0.033 | 1.853 | `t22_probe.py:77 __init__` |
| 938 | 0.060 | 1.810 | `subprocess.py:807 __init__` |
| 938 | 0.134 | 1.707 | `subprocess.py:1791 _execute_child` |
| 1 | 0.002 | 0.673 | `src/crosswire/coverage.py:9 inspect` |
| 938 | 0.666 | 0.666 | `~:0 <built-in method _posixsubprocess.fork_exec>` |
| 30 | 0.001 | 0.615 | `src/crosswire/git.py:272 entries_for_paths` |
| 3749 | 0.609 | 0.609 | `~:0 <built-in method posix.read>` |
| 1 | 0.000 | 0.481 | `src/crosswire/engine.py:187 <listcomp>` |
| 30 | 0.000 | 0.481 | `src/crosswire/git.py:75 resolve` |
| 938 | 0.025 | 0.150 | `<frozen os>:713 copy` |
| 938 | 0.074 | 0.145 | `subprocess.py:1282 _close_pipe_fds` |
| 158552 | 0.055 | 0.084 | `<frozen os>:806 fsencode` |

</details>

<details><summary>depth2 — combined — warm (2.735 s profiled)</summary>

| Calls | Self s | Cumulative s | Function |
| ---: | ---: | ---: | --- |
| 1 | 0.000 | 2.735 | `src/crosswire/cli.py:99 main` |
| 1 | 0.000 | 2.735 | `src/crosswire/cli.py:17 _main` |
| 1 | 0.001 | 2.734 | `src/crosswire/combined.py:172 analyze_combined` |
| 161 | 0.007 | 2.615 | `t22_probe.py:80 run` |
| 161 | 0.006 | 2.601 | `subprocess.py:506 run` |
| 161 | 0.001 | 2.265 | `subprocess.py:1165 communicate` |
| 161 | 0.012 | 2.263 | `subprocess.py:2062 _communicate` |
| 356 | 0.004 | 2.234 | `selectors.py:402 select` |
| 356 | 2.230 | 2.230 | `~:0 <method 'poll' of 'select.poll' objects>` |
| 101 | 0.001 | 1.563 | `src/crosswire/git.py:30 _run` |
| 1 | 0.000 | 1.086 | `src/crosswire/integrate.py:63 integrate` |
| 30 | 0.001 | 1.085 | `src/crosswire/integrate.py:41 _merge` |
| 60 | 0.001 | 1.080 | `src/crosswire/integrate.py:25 _run` |
| 1 | 0.000 | 0.973 | `src/crosswire/combined.py:91 __init__` |
| 1 | 0.002 | 0.603 | `src/crosswire/coverage.py:9 inspect` |
| 32 | 0.001 | 0.581 | `src/crosswire/git.py:272 entries_for_paths` |
| 30 | 0.000 | 0.473 | `src/crosswire/git.py:93 merge_base` |
| 30 | 0.000 | 0.473 | `src/crosswire/git.py:87 _merge_base_sha` |
| 31 | 0.000 | 0.384 | `src/crosswire/git.py:75 resolve` |
| 1 | 0.000 | 0.372 | `src/crosswire/combined.py:97 <listcomp>` |
| 162 | 0.005 | 0.332 | `t22_probe.py:77 __init__` |
| 162 | 0.011 | 0.325 | `subprocess.py:807 __init__` |
| 162 | 0.023 | 0.307 | `subprocess.py:1791 _execute_child` |
| 162 | 0.122 | 0.122 | `~:0 <built-in method _posixsubprocess.fork_exec>` |
| 649 | 0.110 | 0.110 | `~:0 <built-in method posix.read>` |

</details>

