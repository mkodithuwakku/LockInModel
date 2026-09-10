# Documentation guide

Updated September 10, 2026 following the dashboard, reliability, Sleeper, and replay implementation.

1. [Walkthrough](WALKTHROUGH.md): understand the user workflow.
2. [Architecture](ARCHITECTURE.md): follow data through the application.
3. [Model](MODEL.md): inspect equations and tradeoffs.
4. [Configuration](CONFIGURATION.md): understand shared local settings.
5. [Operations](OPERATIONS.md): run, test, and diagnose the app.
6. [Historical replay](HISTORICAL_REPLAY.md): understand the captured fixture.
7. [Known issues](KNOWN_ISSUES.md): review unresolved limitations honestly.

The historical fixture was captured from an immutable third-party archive of NBA API responses after one direct NBA bulk request timed out. Sleeper NBA league import was verified against the user's account. Local tests prohibit network access. No test email was sent; the previously exposed credential is blocked locally.

When changing model or scoring behavior, update the reference and regression tests together. Preserve provenance when recapturing data. Distinguish a functional replay from evidence of predictive accuracy.

- [Test Week](TEST_WEEK.md): simulate morning/night decisions with banked scores and isolated rosters.
