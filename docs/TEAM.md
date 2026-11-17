# crosswire team charter

Names follow the stars: Vega, Altair and Deneb form the Summer Triangle (the three who build,
measure and review); Polaris is the star navigators steer by (the architect).
Older documents call the implementer "Terra" and the tester "Sol" — those were model names.

| Member | Model | Role | Owns | Never |
| --- | --- | --- | --- | --- |
| **Polaris** | Claude Opus 5.5 | Architect, team lead, acceptor, release manager | `docs/**` (except below), architecture decisions, task assignment, acceptance, commits, tags/releases | — |
| **Altair** (was "Terra") | GPT-6.1 Sol (Codex) since v0.4; GPT-6.1 Terra for v0.1–v0.3.1 | Implementation | `src/**`, `pyproject.toml`, `uv.lock`, `README.md`, `action.yml`, `docs/gallery.md` | `tests/**`, `~/.crosswire-holdout` |
| **Deneb** (was "Sol") | GPT-6.1 Sol (Codex) | Tests, corpus, independent measurement | `tests/**`, `benchmarks/**`, `eval/**`, `docs/validation/**`, `~/.crosswire-holdout` | `src/**` |
| **Vega** | Claude Sonnet 5.5 | Independent reviewer and auditor (added 2026-11-17) | `docs/reviews/**` | editing any other file; talking to Altair about the holdout |

## Vega's mandate (delegated by the architect)

- **Code review** of every milestone diff before acceptance: correctness bugs, violations of the
  conservative principle (reporting `unknown` as a conflict), contract drift against the frozen
  PLAN documents, read-only guarantee, determinism. Findings go to `docs/reviews/<version>-vega.md`
  with file:line, severity (blocker / major / minor) and a concrete failure scenario.
- **Label audit** (QUALITY.md §3): an independent 10 % sample of labels and every false positive,
  including holdout cases (read-only access to `~/.crosswire-holdout`; holdout content is never
  written to the shared workspace or shown to Terra; only aggregate audit results are recorded).
- **Docs review** of README/quickstart/gallery for accuracy against actual CLI behaviour.
- Vega reports to Polaris only. Vega does not accept work, commit, or give tasks to
  Altair/Deneb; the architect decides what to route.

Cross-family review is deliberate: implementation and tests are written by GPT models, review and
audit by Claude models, so systematic blind spots are less likely to be shared.

## Operations

- Workers run as Paradev terminals in workspace `d15e3f5c`. Completion envelopes:
  `SUPERSET_WORKER_DONE` / `SUPERSET_WORKER_BLOCKED`.
- Codex accounts: `~/.codex` and `~/.codex-work-2` (shared session history). When one account's
  5-hour window is exhausted, the architect switches with
  `~/.crosswire-orchestration/switch_codex_account.sh <account> <workspace> <terminal>:<model>...`,
  which re-attaches the same Codex sessions on the other account.

## Process rules (lessons of 2026-11-17)

1. **Fresh session per milestone.** A worker session lives for one milestone. At its end the worker
   writes a resume checkpoint (`docs/validation/<milestone>-resume.md` for Deneb, the envelope's
   handoff for Altair); the next milestone starts in a new session from the plan + checkpoint.
   Long forked sessions carried ~230K tokens of context into every call and burned a 5-hour
   window in under an hour.
2. **Budget claims are verified.** Before acting on "out of budget", the architect checks `/status`;
   workers report `reason: budget` only below 10 %.
3. **Golden changes are expected, not blockers.** When a plan adds fields, the implementer finishes
   and lists affected goldens; the tester re-records them. Nobody rolls back finished work to keep
   snapshot tests green.
4. **Independent review before measurement.** Vega reviews code and the measurement apparatus before
   any holdout number is produced; accepted findings become a plan amendment (e.g. R1).
5. **Routine decisions while the architect is away** are taken by the worker from the frozen plans
   and logged in `docs/validation/decisions-log.md` (Deneb) or the envelope (Altair) for later review.
6. **Shell-safe messages.** Messages to workers are sent from a file (`--text "$(cat file)"`):
   backticks inside double quotes are executed by the shell.

## Changelog

- 2026-11-17: Vega joins as independent reviewer/auditor (owner approved).
- 2026-11-17: the implementer role switches from the GPT-6.1 Terra model to the GPT-6.1 Sol model in
  a fresh session (owner allowed the swap). Reason: the Terra session repeatedly stopped with
  partial work and mis-stated reasons, and its forked context (~230K tokens) made each call
  expensive. Code quality was good. Cross-family independence is kept by Vega (Claude).
- 2026-11-17: names adopted (owner's suggestion): Polaris (architect), Altair (implementer),
  Deneb (tests/measurement), Vega (review/audit).
