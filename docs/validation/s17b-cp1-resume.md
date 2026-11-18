# S17b checkpoint (1) — wiring and policy proposal

Task `v0.5-s17b-cp1`, **steps 1–2 complete for Vega diff-check; step 3 NOT executed**. No operational checkpoint or authorization record was created, no API call or real Git clone/fetch occurred, no detector wheel was built, no natural label was produced, and Deneb made no src edit or project commit. Altair's uncommitted T22 source is outside this apparatus and must never supply the detector wheel.

`python -m benchmarks.s17b --acquire --checkpoint <file> --authorization <file> --root <dir>` now performs thin wiring: verify Permit before any side effect/runner, fresh private temporary root, GhGet(Permit), collect_metadata, durable metadata selection, prepare_clone, and prepare_slots(integrate=False) with an injected ObjectStoreTransport and **one shared GitBudget.from_policy** for initial history plus all heads across repositories. API metadata and every acquisition outcome remain durable local evidence; existing roots refuse replay. There is no checker, detector, virtual integration, label or checkpoint-(2) path. Exit 1 describes incomplete acquisition. Fake-runner tests prove the gates, byte sharing, default/head pin flow, ceiling and selected-slot preservation; they manufacture neither an operational checkpoint nor authorization file.

Proposed policy pins: cutoff **2026-11-18T00:00:00Z**, API **2022-11-28**, actual first `gh --version` line **gh version 2.102.0 (2026-09-30)**. Exact controller Python and Git versions are in policy and remain checked by Permit. Repository membership, seed/order, budgets, metadata filters and graph rules are unchanged.

**Detector revision timing:** policy's review-time `detector_commit` is `30ff34363070175160e066dd1b5743856c907a05` (HEAD when preparing these steps). It is provisional until checkpoint creation: after Vega checks this wiring and Polaris authorizes step 3, re-read `git rev-parse HEAD` and set `detector_commit` to that exact full SHA immediately before writing checkpoint (1). If Polaris has committed this wiring meanwhile, the reviewed policy's sole detector-SHA refresh and resulting policy/hash map must be reported with the checkpoint. Never pin or build from the dirty worktree. The future wheel is built from **git archive of the recorded commit**, not from local src; no wheel build is part of this task stage.

Pending step 3, only after Vega diff-check and Polaris authorization: write checkpoint (1) exclusively to **`~/.crosswire-evidence/s17b/checkpoint-1.json`**, report its file SHA-256 and canonical policy SHA-256, then stop for Polaris to create authorization. Do not overwrite or create that file from this resume note alone. No tool opened or listed the evidence directory in this stage.

Permit expects an authorization JSON object with these exact required fields (additional fields are not checked):

```json
{
  "checkpoint_sha256": "<64 lowercase hexadecimal SHA-256 of exact checkpoint-1.json bytes>",
  "scope": "S17b read-only acquisition",
  "approved_by": "Polaris"
}
```

Polaris writes that record himself, for example at `~/.crosswire-evidence/s17b/authorization.json`. This schema is documentation only, not an authorization record. The guard is procedural and unsigned. Its scope covers only acquisition, not checkpoint (2), measurement orchestration or labels. Permission also verifies code hashes, ready status, Python/Git versions and fixed cutoff. It cannot be inferred from tests or populated policy pins.

Authorized future collection command (shown for review, **not run**):

```sh
.venv/bin/python -m benchmarks.s17b --acquire --checkpoint ~/.crosswire-evidence/s17b/checkpoint-1.json --authorization ~/.crosswire-evidence/s17b/authorization.json --root "$S17B_ROOT"
```

Choose `S17B_ROOT` as a fresh system-temporary-directory child before collection. All per-case/API/graph evidence follows D-Ev1; no large evidence enters git. This command's immutable checkpoint pins reviewed source/tests/policy, whereas the installed detector archive provenance belongs to checkpoint (2). The 90-minute measurement ceiling remains the later orchestrator's obligation.

Validation for steps 1–2: **117 passed in 55.02 seconds** across tests/test_s17b_*.py, including nine new entry-point tests with fake runners/transports. CLI help and diff whitespace checks pass. No background job remains from this task.
