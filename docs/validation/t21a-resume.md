# T21a Deneb checkpoint

Task: `v0.5-t21a`. Status: active; replace this status with the final result before handoff.

The runnable comparator is `benchmarks/t21_equality.py`, with release-suite input collector `benchmarks/t21_capture.py` and 15 passing negative-control tests in `tests/test_t21_equality.py`. The tag's 449 tests passed during harvesting. Inputs: 577 original snapshots compacted to 334 distinct fixtures, retaining 782 original CLI invocations. Details and reproduction commands are in `docs/validation/t21a.md`; annotated tag/commit/source-tree provenance is `t21a-provenance.json`.

Active process: PID 17657, exec session 59904, command:

```sh
.venv/bin/python benchmarks/t21_equality.py \
  --baseline /tmp/crosswire-t21a-release --candidate /tmp/crosswire-t21a-head \
  --record-baseline --resume-recording --jobs 12
```

The baseline export is tag `v0.4.0`, annotated object `b97f209f364580fa1cfcf8a93827ac8e95fb5763`, commit `9bcce0fe75100712b1b34b91b48afa891019fdbe`. The candidate export is starting HEAD `2cb3a06cf2084292d9732fc44c03891de636d866`; its source tree equals the tag. Altair's shared-worktree edits began during construction, so this self-check intentionally measures the immutable HEAD export, not those evolving edits.

Recording is complete: 334 fixtures, **43,726 records**. The immutable manifest SHA-256 is `98fb360c5a07e8a2cec9dfcc359b6ca92d276a8a8e177f3d07f431fc269c692c`. The existing process is replaying both source exports against all frozen streams (87,452 executions total); no equality verdict yet. Do not launch another comparator while it owns `/private/tmp/crosswire-t21a-fixtures.lock`; fixture paths are intentionally fixed. Observe the existing process/session and final report `docs/validation/t21-self-check.json`. The compressed actual-output stream is not complete until that report is written.

Completed expected-byte files are never replaced. An unfinished recording has `recording-checkpoint.json`, per-file hashes, archived recorder revisions and `recording-context.json`; `--resume-recording` checks those completed files before generating pending ones. A finalized manifest refuses record mode; subsequent ordinary invocations replay immutable expectations. Do not change the comparator/collector after the manifest is finalized without an explicit provenance amendment; normal comparison rejects harness drift.

Remaining before completion: finish the full self-check, inspect all mismatches/errors (none may be discarded), record final counts and manifest hash in the report/checkpoint, verify authorized files and unchanged public sealed apparatus, then emit the worker envelope. No S16/S17/S18 work, oracle labels, private holdout access or project Git mutations have been performed in this task. Vega must independently compare the recorded raw bytes; the live T21b/c candidate and acceptance/performance gates remain separate work.
