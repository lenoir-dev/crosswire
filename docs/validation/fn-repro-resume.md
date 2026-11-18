# BF1 reproduction checkpoint — Deneb

Task `v0.5-fn-repro`: `tests/test_fn_reexport_move.py` follows [Vega’s mutation audit, section 3](../reviews/v0.5-mut-vega.md). Target `pkg.py` re-exports `unittest.TestCase`; A moves the module; B uses either `pkg.TestCase` or `from pkg import TestCase`. Pairwise detects both. Combined/plan are four `xfail(strict=True, raises=AssertionError)` regressions. A control defining the same class locally is detected by all three modes in both forms. No separate root-cause analysis is added; Vega’s analysis is authoritative. This is BF1 for Altair after T22. No src edits or commits by Deneb.

Validation: **8 passed / 4 strict xfailed**; the combined S17b/BF1/adapter check also passes with the same four expected failures.
