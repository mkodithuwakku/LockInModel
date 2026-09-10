# Historical replay: captured 2025–26 dataset

## What is stored

The first fixture was captured on September 10, 2026 from an immutable revision of [llimllib/nba_data](https://github.com/llimllib/nba_data), which archives NBA API data. A direct NBA bulk attempt timed out; subsequent historical capture used the archive and did not retry NBA Stats.

| Component | Coverage |
| --- | --- |
| Observed player games | 26,648 regular-season player-game rows; 582 players |
| Schedule | Finalized regular-season team-game records |
| Prior input | 2024–25 regular-season player game observations |
| Test week | December 22–28, 2025 |
| Default replay date | December 25, 2025, end of day |
| Selection | Seed 202526, recorded pool of complete representative weeks |

Exact source revision, file hashes, row counts, coverage dates, and selection parameters are in [the committed manifest](../data/fixture-manifest.json). Raw and normalized datasets are local ignored files.

## Capturing and resuming

`python capture.py` obtains the source revision once, saves raw Parquet files, and reuses existing files on later invocations. A download is parsed before becoming a completed raw file. Normalized outputs are written through temporary files. The manifest is published after validation succeeds.

The source archive's player tables use newer box-score column names and lack dates, so capture joins them to team-game records using game and team IDs. It excludes DNP/zero-minute rows, retains regular-season game prefixes, checks duplicate player-game rows, verifies complete pairs of team records, and preserves source IDs.

It chooses a Monday–Sunday week from the recorded eligible pool only when all 30 teams are represented and each scheduled game has player observations. The full season is kept so additional replay windows can be implemented without another player-level capture.

## Offline execution

`FixtureProvider` verifies checksums before reading local tables. It exposes observations and schedule information to the shared engine. It never falls back to live endpoints.

The engine filters observations at the selected date before computing player statistics and pickup signals. A regression test changes every future point total and verifies that earlier decisions and candidate rankings remain identical.

## Prior policy

The fixture uses a **2024–25 per-game average** recomputed with the selected team's supported weights, including derived bonuses. This is a prior-season average, not a career average. Players without prior-season observations use the recent-history/rookie guard path.

Current career averages were deliberately not captured because they would contain future information relative to the test week. The changed prior policy is recorded in the manifest and should remain explicit in any comparison with the original model.

## Schedule and ownership limitations

The schedule is a finalized historical schedule. It does not recreate postponement/rescheduling information as known on each original day. Remaining games are counted from the last observed team assignment, so historical trades during a replay window require more precise transaction data for strict fidelity.

A team-game opportunity does not guarantee the player participates. Injury news and historical expected minutes are not reconstructed. Current Sleeper rosters are useful for product testing but are not historical ownership snapshots. Local rosters also lack complete league ownership information.

Technical and flagrant foul penalties are not present in this fixture. Imported leagues with those rules display partial estimates and withhold lock recommendations rather than claiming exact Sleeper scores.

## Data layout

```text
data/
  fixture-manifest.json        # committed provenance
  cache/archive/              # ignored raw downloads and revision
  cache/http/                 # ignored live response cache and cooldowns
  cache/portraits/             # ignored local headshots
  fixtures/2025-26/
    manifest.json
    games.parquet
    schedule.parquet
    priors.parquet
```

## Evaluation milestone

This week is a repeatable engineering fixture, not evidence of model quality. Before reporting performance, define the exact sequential lock policy, what happens after missed final opportunities/DNPs, and whether decisions happen at noon or after every game.

Evaluate across multiple independent weeks and compare retained FP, regret against the hindsight best eligible score, and coverage against simple first-game/final-game policies. Keep tuning and held-out weeks separate. Assess raw model probability calibration separately from the heuristic-adjusted lock score.
