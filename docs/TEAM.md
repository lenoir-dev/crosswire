# crosswire team charter

| Member | Model | Role | Owns | Never |
| --- | --- | --- | --- | --- |
| Opus | Claude Opus 5.5 | Architect, team lead, acceptor, release manager | `docs/**` (except below), architecture decisions, task assignment, acceptance, commits, tags/releases | — |
| Terra | GPT-6.1 Terra (Codex) | Implementation | `src/**`, `pyproject.toml`, `uv.lock`, `README.md`, `action.yml`, `docs/gallery.md` | `tests/**`, `~/.crosswire-holdout` |
| Sol | GPT-6.1 Sol (Codex) | Tests, corpus, independent measurement | `tests/**`, `benchmarks/**`, `eval/**`, `docs/validation/**`, `~/.crosswire-holdout` | `src/**` |
| Vega | Claude Sonnet 5.5 | Independent reviewer and auditor (added 2026-11-17) | `docs/reviews/**` | editing any other file; talking to Terra about the holdout |

## Vega's mandate (delegated by the architect)

- **Code review** of every milestone diff before acceptance: correctness bugs, violations of the
  conservative principle (reporting `unknown` as a conflict), contract drift against the frozen
  PLAN documents, read-only guarantee, determinism. Findings go to `docs/reviews/<version>-vega.md`
  with file:line, severity (blocker / major / minor) and a concrete failure scenario.
- **Label audit** (QUALITY.md §3): an independent 10 % sample of labels and every false positive,
  including holdout cases (read-only access to `~/.crosswire-holdout`; holdout content is never
  written to the shared workspace or shown to Terra; only aggregate audit results are recorded).
- **Docs review** of README/quickstart/gallery for accuracy against actual CLI behaviour.
- Vega reports to the architect only. Vega does not accept work, commit, or give tasks to
  Terra/Sol; the architect decides what to route.

Cross-family review is deliberate: implementation and tests are written by GPT models, review and
audit by Claude models, so systematic blind spots are less likely to be shared.

## Operations

- Workers run as Paradev terminals in workspace `d15e3f5c`. Completion envelopes:
  `SUPERSET_WORKER_DONE` / `SUPERSET_WORKER_BLOCKED`.
- Codex accounts: `~/.codex` and `~/.codex-work-2` (shared session history). When one account's
  5-hour window is exhausted, the architect switches with
  `~/.crosswire-orchestration/switch_codex_account.sh <account> <workspace> <terminal>:<model>...`,
  which re-attaches the same Codex sessions on the other account.
