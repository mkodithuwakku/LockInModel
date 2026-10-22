# Relearning LockIn

## The decision you built it for

A player may play several times during a fantasy week, but only one chosen performance counts in a lock-in format. The application evaluates whether the latest completed score is worth keeping or whether remaining opportunities justify waiting.

It does not submit the decision to Sleeper. It also does not infer that you have already locked a player: existing lock selections are not imported.

## Daily workflow

Open the dashboard and choose a team. A compact header leads directly to the roster sheet; summary counters and supporting context follow below the full roster. The roster shows the latest score, recent baseline, remaining opportunities, and a decision status. Open a player to inspect actual observed game history and the explanation behind the recommendation.

The dashboard uses a compact neutral-charcoal lineup layout with colored position slots, small headshots, NBA team/injury labels, and a seven-day opponent strip. Recommended starters from the latest refresh, bench, and reserve players are grouped separately. Upcoming game tiles show **Proj** fantasy points for each matchup across the week, using the saved per-game baseline without opponent adjustment. Completed performances show observed **Final** points; missing values stay dashes and an unknown schedule shows question marks rather than off days. Subtle gold indicates LOCK, muted steel indicates WAIT, and warm amber indicates a review requirement, such as an unavailable schedule or incomplete scoring. Each state also has a text label. A lock score is a heuristic preference; it is not calibrated confidence.

On phones, teams scroll horizontally and roster rows prioritize the latest score and decision; open player details for the baseline and history. A skip link and visible keyboard focus support navigation. Test Week's nightly box scores are expandable so the roster remains easier to reach.

**Recent form** gives a compact individual-performance view below the full roster on every screen. The recommended lineup itself is the roster sheet above, with its dated summary. Five players appear initially, ranked by their average over up to five observed games. Each row shows a sparkline, sample size, average FP, change versus the previous five games when ten observations exist, and verified remaining opportunities. Expand to see everyone or select a row to open that player's details. A dash means unavailable, not zero. Stale reports label this saved history; the panel is descriptive, not a projection. Pickup research remains in **On the rise**; the decorative court, sidebar watchlist, and explanatory filler have been removed.

Sleeper rosters are managed in Sleeper; the local app's **Refresh live data** also checks for new leagues and updates memberships. The hosted site's **Reload report** only reloads the published snapshot; it cannot start a Mac refresh. Original local teams are separated into Test Week practice templates. In Test Week, **Edit roster** changes only that saved practice run; email always uses normal teams.

## Replay versus live

**Test Week** starts Monday morning, December 22, 2025. Reveal each night, inspect box scores and model calls, bank a score per starter, and move to the next morning. Progress persists through Sunday, December 28. The morning hides that night’s outcomes; banked scores stay fixed as later performances appear. [Full simulator guide](TEST_WEEK.md).

Live analysis is an explicit refresh. It uses completed observations through the refresh day (same-day scores require schedule-confirmed finals), counts remaining schedule opportunities, and labels unavailable data. Before regular-season games enter the observation cutoff, the report shows UPCOMING and previews the opening-week schedule without requesting NBA Stats. A drafted fantasy league is not proof that the NBA regular season has begun. Roster, schedule, and performance availability are handled separately. Merely opening the dashboard does not start NBA retrieval. Saved live reports expire after 26 hours or when their fantasy week ends; their original timestamp remains visible across midnight within the same week.

Completed, pre-draft, and drafting leagues display their state without NBA analysis. A newer imported season archives older teams; enable **Show archived leagues** locally to view them. Daily refreshes discover the current season (2026 for 2026–27), falling back to the last saved season until new leagues exist. The email automation targets noon; the website publisher targets 7:00 AM America/Edmonton and catches up after sleep/login. Neither is a continuous live-game feed.

Live observations accumulate in one local SQLite database and are shared across leagues. The Mac generates a public report and website assets, then pushes them to GitHub Pages. The website remains readable while the Mac is off, but new reports need the Mac awake, logged in, and online. It has no separate database. See [Hosting](HOSTING.md).

## How the lock model reasons

Suppose a player usually produces 35 FP with a 10-FP standard deviation and just scored 45. The Normal model estimates a 15.9% chance that one future game exceeds 45. With one game left, the initial lock probability is 84.1%; with three left, it is approximately `0.8413³ = 59.6%`.

More opportunities make waiting more attractive. The application then adjusts for rarity, sample size, and configured preferences. This is an explicit statistical rule, not a trained machine-learning model or an optimal-stopping solver.

## How the pickup finder reasons

A single outstanding performance can be a good score to lock without indicating that the player is a good long-term pickup. The finder compares the last five observed games against a separate earlier window of up to 20 games.

It asks whether FP increased, whether minutes increased, how consistently the player exceeded their baseline, and whether unusually strong shooting or steals/blocks account for the improvement. An estimated projection is compared with a position-compatible roster alternative, preferring bench players when available.

For imported leagues, every team's roster is used to identify unrostered players. For local sample teams, league ownership is unknown. During replay, imported ownership remains a current snapshot and must not be interpreted as historical availability.

## Scoring and data limitations

Bonuses are computed from each observed box score. Double/triple-double and configured positive thresholds for points, rebounds, assists, steals, and blocks stack; 15+ assists and 20+ rebounds are supported examples. Each league retains its own weights, so new milestone rules need configuration rather than team-specific code. See [Configuration](CONFIGURATION.md) for naming and import rules.

Technical and flagrant foul penalties (`tf`, `ff`) are omitted and retained in `ignored_scoring` metadata. Personal fouls (`PF`) use actual values when available and are omitted otherwise. Offensive/defensive rebound weights use actual splits when available; otherwise the model uses total rebounds with coefficient `REB weight + (OREB weight + DREB weight) / 2`, treating an absent split weight as zero. Equal split weights are exact; unequal weights are an approximation. These approved adjustments are shown as information and do not block recommendations. Other unknown nonzero rules still withhold actionable recommendations.

## Interview description

> I built an NBA fantasy decision dashboard with read-only Sleeper synchronization, league-specific scoring, and explainable lock/wait and pickup heuristics. One local SQLite database retains live observations. A Mac scheduler publishes static reports to GitHub Pages with catch-up, retries, and deployment confirmation, so the website needs no database server. Separate checksum-verified fixtures support offline practice, and the engine excludes future observations from replay inputs.

Discuss database upserts versus immutable replay, local availability versus static hosting, deployment confirmation versus a successful push, extensible scoring versus approximation error, and the model's independence assumption. No performance improvement has yet been established through held-out evaluation.

## Recommended lineup

Select a team to see the latest refresh’s **Recommended lineup** directly in the roster sheet. The summary shows the report day, projected FP total, and filled slots. Recommended starters occupy their assigned league positions; other players appear under Bench or reserve with exclusion reasons. Full roster, Lineup, and Bench filters use these displayed assignments. Player cards still open the same player details.

The optimizer can promote bench players and move flexible players between eligible positions. Unfilled positions and partial inputs stay explicit; when no starts are available, a compact slot strip avoids a wall of empty cards. An unavailable or mismatched plan falls back to a clearly labeled synced roster. Test Week retains manual starter selection and a separate pregame preview.

The date and Snapshot details identify when the plan was saved. Midnight does not erase it, and a failed refresh retains the older dated plan; freshness notices still apply to lock/pickup decisions. After adding or dropping players in Sleeper, refresh and publish from your Mac. Reload on the hosted site only reads that publication. The display never changes the actual Sleeper lineup. Check existing locks and tipoffs there before acting.

NBA team abbreviations in roster cards include a small decorative team logo (14px, or 12px on phones). Logos load from the NBA CDN; unknown/free-agent teams and failed images retain text only.

## Season review and badge race

Switch to **Season review** in the main navigation to see every published team's season production, scored under that league's formula. Select a team card for its detailed breakdown:
- **Production summaries:** Roster FP, FP per player appearance, coverage, top-3 contributor share, and aggregate box-score shooting percentages.
- **Key players:** Season anchor (highest total FP), per-game leader (highest average), form leader (largest recent 5-game vs preceding 5-game change), and biggest swings (largest FP standard deviation).
- **Season Badge race:** Tracks cumulative awards for all 44 badges across the season. Switch between **My roster** and **NBA-wide** views, review category leaders, or expand individual badge categories. Selecting any player opens their expanded card with season award counts and repeat counts.

## Badge guide

Select **Badge guide** in the top bar to inspect all 44 daily indicators in a scrollable reference dialog. The guide covers:
- **Single-game milestones:** 30–70 points, 10–20 assists, 10–20 rebounds, 5–10 threes, 10 steals, and 10 blocks (highest qualifying tier awarded per stat).
- **NBA-wide leaders:** Top-3 finishes in threes, field goals, boards, steals, blocks, minutes, assists, free throws, turnovers, and missed shots, plus double-doubles (☕) and triple-doubles (🎩).
- **Contextual fantasy leaders:** League-scored leaders in wins/losses, home/away, ages 32+ and 23-and-younger, 3-game heater/cold-spell streaks, and assist-to-turnover margins (Butterfingers).
- **League-scored projection surprises:** Above/below expectation comparisons powered by archived pregame forecasts.

