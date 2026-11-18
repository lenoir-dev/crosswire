# v0.1 public-output snapshots

`v01.json` contains 155 outputs from the 187-test v0.1 scenario suite, recorded
from commit `562deeb51105bdf2b5d89a202878ec50e9d3f6d2` in an isolated Git worktree.
The recorder imported `crosswire` from `${TMP}/crosswire-sol-v01-562deeb/src`, which
was verified separately before accepting the recording. All 187 tests passed.

The helpers capture each successful `analyze()` result and CLI exit 0/1 output.
Every existing engine scenario also runs through `python -m crosswire check
--format json`. CLI text and GitHub scenarios retain exact stdout/stderr bytes
as decoded text. Fixed Git metadata makes fixture SHAs reproducible; findings
and their order are not normalized. Version/help output and exit-2 diagnostics
are excluded because v0.2 intentionally extends options and unknown-ref errors.

Ordinary pytest runs verify known scenario outputs against the recording.
New v0.2 scenarios have separate contract assertions and cannot silently replace
the v0.1 baselines. To reproduce the recording from the project root:

```sh
git worktree add --detach ${TMP}/crosswire-sol-v01-562deeb 562deeb
CROSSWIRE_GOLDEN_RECORD=1 \
CROSSWIRE_GOLDEN_SOURCE=${TMP}/crosswire-sol-v01-562deeb/src \
PYTHONPATH=${TMP}/crosswire-sol-v01-562deeb/src \
uv run pytest -q tests/test_git.py tests/test_python_analyzer.py \
  tests/test_diffing.py tests/test_rules.py tests/test_cli.py tests/test_amendment_a1.py
```

Use a different temporary worktree path if that directory already exists, and
set both source environment variables to its `src` directory. Do not regenerate
the snapshots against current sources to make a failing regression pass.

Amendment A2 explicitly permits re-recording CW005 orientation only. The original
recording is archived byte-for-byte as `v01-original.json`, pinned by SHA-256 in
`test_golden_a2.py`. Run `uv run python tests/refresh_a2_goldens.py` to refresh only
CW005-containing outputs. The guard proves that all other outputs remain exact
and permits only canonical branch/other_branch/message changes within CW005.

PLAN-v0.3b T12 permits coalescing findings by owner/file/symbol at the first use.
`v02-pre-t12.json` is the pinned pre-change archive. Re-record with
`uv run python tests/refresh_t12_goldens.py`; that command approves exactly nine
affected outputs and rejects changes to the remaining 146. `test_golden_t12.py`
and the original A2 guard enforce both amendments independently of production helpers.

Publication correction: Polaris authorised replacing machine-specific paths in
provenance with portable tokens before the repository becomes public. All four
recordings retain exactly their prior `cases` payloads. The checksum guards now
bind the tokenised files; pre-publication and current hashes are recorded in
`docs/validation/v04-golden-audit.json` and
`docs/validation/v04-publication-portability.json`. This is a provenance-only
exception, not permission to re-record or weaken historical finding assertions.

## Commit IDs after the 2026-11-18 history rewrite

The recordings and their integrity hashes are kept byte-for-byte, so they still name the
pre-rewrite commit IDs. The history was rewritten once (author e-mail and local paths scrubbed before
the repository went public); the same commits now have these IDs:

| recorded | current |
| --- | --- |
| `562deeb` | `31acb87` |
