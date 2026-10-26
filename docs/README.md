# Documentation guide

The project-level [README](../README.md) is the portfolio overview and technical walkthrough. [Repository instructions](../AGENTS.md) require it and affected guides to be reviewed with every code change.

1. [Walkthrough](WALKTHROUGH.md): understand the user workflow.
2. [Architecture](ARCHITECTURE.md): follow shared SQLite history, providers, reports, and the static export boundary.
3. [Model](MODEL.md): inspect scoring, configurable milestones, daily lineup assignment, fallbacks, equations, and assumptions.
4. [Configuration](CONFIGURATION.md): configure leagues, formulas, and local publication settings.
5. [Operations](OPERATIONS.md): run, test, back up, and diagnose the app; distinguish email from website publication.
6. [Hosting](HOSTING.md): publish from the Mac to GitHub Pages, handle catch-up/retries, and ship source changes.
7. [Test Week](TEST_WEEK.md): practice morning/night decisions with banked scores and isolated rosters.
8. [Historical replay](HISTORICAL_REPLAY.md): understand immutable fixtures and their separation from live history.
9. [Known issues](KNOWN_ISSUES.md): review unresolved limitations honestly.
10. [Season review](SEASON_REVIEW.md): all-team production summaries, weekly production per appearance, key player highlights, normalized cross-team comparison, the weekly Shaqtin' a fool lock audit, full-season Badge race, and player season badge cards.

The historical fixture was captured from an immutable third-party archive of NBA API responses after one direct NBA bulk request timed out. Sleeper NBA league import was verified against the user's account. Local tests prohibit network access. No test email was sent; the previously exposed credential is blocked locally.

When changing model or scoring behavior, update the reference and regression tests together. Preserve provenance when recapturing data. Distinguish a functional replay from evidence of predictive accuracy.

The [screenshot notes](screenshots/README.md) distinguish the captured generic layout from new scoring/publication behavior that those images do not demonstrate.

- [Projections](PROJECTIONS.md): documents full-roster forecast coverage, source precedence, stat normalization, and expected milestone bonuses.
- [Performance colours](PERFORMANCE_COLOURS.md): personal-average comparisons for completed games, roster tiles, and expanded player cards.
- [Daily badges](DAILY_BADGES.md): icon meanings, 44 indicators, NBA-wide ranking, ties, date expiry, and screenshot scope.

## Agent and developer references

- [Agent Architecture & Data Map](agents/ARCHITECTURE_MAP.md): module map, SQLite schema definitions, and data contracts.
- [Agent Workflows & Testing](agents/WORKFLOWS_AND_TESTING.md): test suite execution, code conventions, and verification steps.

## Delivered epics and future proposals

- [Model evaluation](epics/MODEL_EVALUATION.md): implemented via `evaluator.py` (MAE/RMSE/bias/correlation, walk-forward backtests, sequential solo weekly-lock regret vs Oracle, and `--mode team-weekly` slot-constrained roster regret vs `TEAM_ORACLE`) and `model_check.py` biweekly LaunchAgent.
- [Opponent-aware player projections](epics/OPPONENT_AWARE_PROJECTIONS.md): implemented and promoted to production — pregame features in `features.py`, closed-form Ridge component regressions in `model_ml.py`, per-tile `proj_fp` in `week_games`, and per-game opponent means in lock/wait decisions.
- [Locked-player pinning](epics/LOCKED_PLAYER_PINNING.md): implemented and live on `main` — serverless write bridge, optimizer pinning semantics, and client-side lineup re-pinning for managers in Sleeper lock-in mode. Manual flags are deployed and tested; the matchup-score auto-detection phase remains planned.
- [Roster- and slot-aware lock decisions](epics/ROSTER_AWARE_LOCK_DECISIONS.md): implemented and merged to `main` — Stage 2 open-slot contention pass (`decide.apply_roster_lock_context`) using Hungarian maximum-weight assignment over teammates' expected weekly ceilings, modal-only contention reasoning in `row["reason"]`, and `--mode team-weekly` evaluation.
- [Static export efficiency](epics/STATIC_EXPORT_EFFICIENCY.md): proposed; planning only for shared player identities, on-demand resources, safe caching and compact JSON. No export changes are implemented by this document.
