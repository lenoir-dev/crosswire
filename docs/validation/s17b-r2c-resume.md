# S17b round-2 conditions — Deneb

Task `v0.5-s17b-r2c`: R2-C1/C2 and m1–m4 are implemented for Vega's diff-check. **No real API call/fetch, natural observation/label, operational round-2 checkpoint, src edit or project commit.** Existing T22 changes remain Altair's. Round-1 evidence is untouched.

R2-C1/D-R2d: PR-scoped detail/timeline/files Incomplete after retries produces a cached metadata-unavailable stub without timestamps; unchanged detail_filter emits invalid-metadata, no slot. Cause records retain HTTP/exit status and all attempt evidence. A commit-list failure is cached, makes each selected affected pair unlabelled and consumes that slot. Five distinct failed PRs across both phases stop only that repository; no more API/head fetches for its selected tail. Ceilings/rate stops and terminal health are not PR stubs. The shared client registry prevents PR reuse or phase transitions from resetting failure counts/caches.

R2-C2 pins 120 seconds for PR-scoped GETs; other GETs stay 60 seconds. Tests model round 1's failing-timeline shape end to end with both a permanent 404 and three exhausted fake 120-second timeouts: the initial pair survives, all failed-PR partners get invalid-metadata/no slot, later pairs and the next repository still acquire. Neither model asserts the lost real cause. No actual sleep, API or fetch is used.

m1 stops the reverse chronological ancestry search at the first crossing; a 1,000-old-commit fake graph proves old-history per-commit calls are absent. m2 pins a durable 900-second total cohort wait allowance; reservations precede sleeps, interrupted reservations remain charged on restart, and excess is a global rate-limit stop. m3 preserves unknown stderr/status without retry. m4 emits per-repository PR failures, retries by cause, completed/reserved/unconfirmed waits, and pre-update rescue outcome counts/reasons. Round-1 output remains beside round 2.

**D-R2c disclosure:** it was adopted after one observed round-1 integrated-earlier-pr graph exclusion; the pair's oracle status is unknown. The same structural rule applies to every pair, without semantic outcomes. This is now explicit in P6, the design, README and this report. Prior default merges can still make a candidate fail strict B2; no alternative older candidate is tried.

Selection.py, M3, anchors, own-base and B2 function bytes and all round-1 policy values are unchanged. Round-2-only changes remain within round_id/apparatus. Detector stays 30ff343. Tests and implementation hashes are recorded in s17b-implementation.json. Next: Vega diff-check, then Polaris separately authorizes round-2 checkpoint (1); do not write it from this note.

Validation: `.venv/bin/python -m pytest -q tests/test_s17b_*.py --maxfail=3` — **193 passed** (26.27 s), including 22 R2-C1/C2/minor regression cases. The failing-timeline tests use permanent 404 and exhausted fake timeout replies; real GitHub behavior and the lost round-1 cause remain unverified.
