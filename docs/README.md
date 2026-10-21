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

The historical fixture was captured from an immutable third-party archive of NBA API responses after one direct NBA bulk request timed out. Sleeper NBA league import was verified against the user's account. Local tests prohibit network access. No test email was sent; the previously exposed credential is blocked locally.

When changing model or scoring behavior, update the reference and regression tests together. Preserve provenance when recapturing data. Distinguish a functional replay from evidence of predictive accuracy.

The [screenshot notes](screenshots/README.md) distinguish the captured generic layout from new scoring/publication behavior that those images do not demonstrate.

[Projections](PROJECTIONS.md) documents full-roster forecast coverage, source precedence, stat normalization, and expected milestone bonuses.

- [Daily badges](DAILY_BADGES.md): icon meanings, NBA-wide ranking, ties, date expiry, and screenshot scope.

## Future epic proposals

- [Opponent-aware player projections](epics/OPPONENT_AWARE_PROJECTIONS.md): planning only. Audits existing data, investigates additional sources, proposes stat-level player/opponent interactions, and defines sustainable ingestion, evaluation gates, and an implementation backlog. It does not enable matchup adjustments or authorize data subscriptions.
