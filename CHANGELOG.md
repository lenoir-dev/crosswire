# Changelog

## 0.4.0 — 2026-11-18 (first public release, alpha)

- Pairwise check (CW001–CW005), combined N-branch check with minimal culprit sets (CW006) and
  `crosswire plan` (safe merge order, atomic groups, blocked branches with reasons and hints).
- Diagnostics: remediation hints, exact reproduction commands, per-finding limitations, report-level
  coverage (`complete` / `bounded` / `partial`) with counted gaps.
- Stable JSON (versions 1 and 2) with shipped JSON Schemas (`crosswire schema`), SARIF and GitHub
  annotations, a composite GitHub Action, an on-disk cache.
- Robust against unparsable/oversized/non-UTF-8 sources, shallow clones, unborn branches, bare repos.
- Quality: development-data pilot only (see `docs/validation/v0.4.md`); the sealed holdout is first
  measured for 0.5.
