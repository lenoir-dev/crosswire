# S17b E1/E2 conditions — Deneb

Task `v0.5-s17b-e`: prepared for Vega's diff-check; **no operational checkpoint (1), authorization file, API call, real fetch, label, source edit or project commit**.

E1: the latest required terminal event must be within `terminal_event_tolerance_seconds` of both the PR terminal field and the last terminal-event timestamp. Signed field skew, last-terminal gap and tolerance are recorded. Production metadata/filter paths pass the policy to the proof. Vega's merged event followed one second later by closed now passes; 60 seconds passes and 61 fails. A custom one-second policy regression proves the value is used rather than a hard-coded 60. The ten-PR health stop is unchanged. Policy/design/README wording matches the code.

E2: `Permit.prepare_clone(directory, repository, branch, expected, budget, **kwargs)` forwards named arguments explicitly, including permit and budget. The natural positional-budget call executes through the real acquisition function with fake permission, transport and Git runner; it preserves pinned-SHA/byte accounting without creating checkpoint/authorization files or making a real fetch.

All six focused regression invocations failed before correction (including missing gap metadata and the policy-argument test); the conditions module passes afterwards. The successor implementation snapshot records final suite counts and hashes, not an operational freeze. Next: Vega diff-checks E1/E2, then Polaris separately authorizes checkpoint (1). The optional checkout minor and later measurement-time orchestration are unchanged by this two-condition task.

Final validation: **108 passed in 52.03 seconds** across tests/test_s17b_*.py; focused conditions module 30 passed. Diff whitespace check clean. No background job remains from this task.
