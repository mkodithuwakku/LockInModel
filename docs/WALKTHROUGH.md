# Relearning LockIn

## The decision you built it for

A player may play several times during a fantasy week, but only one chosen performance counts in a lock-in format. The application evaluates whether the latest completed score is worth keeping or whether remaining opportunities justify waiting.

It does not submit the decision to Sleeper. It also does not infer that you have already locked a player: existing lock selections are not imported.

## Daily workflow

Open the dashboard and choose a team. The roster shows the latest score, recent baseline, remaining opportunities, and a decision status. Open a player to inspect actual observed game history and the explanation behind the recommendation.

Mint indicates LOCK and lavender indicates WAIT. Amber indicates a review requirement, such as an unavailable schedule or incomplete scoring. A lock score is a heuristic preference; it is not calibrated confidence.

Sleeper rosters are managed in Sleeper; **Refresh live data** also checks for new leagues and updates memberships. Original local teams are separated into Test Week practice templates. In Test Week, **Edit roster** changes only that saved practice run; email always uses normal teams.

## Replay versus live

**Test Week** starts Monday morning, December 22, 2025. Reveal each night, inspect box scores and model calls, bank a score per starter, and move to the next morning. Progress persists through Sunday, December 28. The morning hides that night’s outcomes; banked scores stay fixed as later performances appear. [Full simulator guide](TEST_WEEK.md).

Live analysis is an explicit refresh. It uses completed observations through the previous day for a noon report, counts remaining schedule opportunities, and labels unavailable data. Merely opening the dashboard does not start NBA retrieval. Saved live reports become stale after six hours or a date change, at which point lock recommendations are withheld until refreshed.

Completed, pre-draft, and drafting leagues display their state without NBA analysis. A newer imported season archives older teams; enable **Show archived leagues** to view them. The daily automation and live refresh discover the current season (2026 for 2026–27), falling back to the last saved season until new leagues exist. The automation runs at noon, not continuously.

## How the lock model reasons

Suppose a player usually produces 35 FP with a 10-FP standard deviation and just scored 45. The Normal model estimates a 15.9% chance that one future game exceeds 45. With one game left, the initial lock probability is 84.1%; with three left, it is approximately `0.8413³ = 59.6%`.

More opportunities make waiting more attractive. The application then adjusts for rarity, sample size, and configured preferences. This is an explicit statistical rule, not a trained machine-learning model or an optimal-stopping solver.

## How the pickup finder reasons

A single outstanding performance can be a good score to lock without indicating that the player is a good long-term pickup. The finder compares the last five observed games against a separate earlier window of up to 20 games.

It asks whether FP increased, whether minutes increased, how consistently the player exceeded their baseline, and whether unusually strong shooting or steals/blocks account for the improvement. An estimated projection is compared with a position-compatible roster alternative, preferring bench players when available.

For imported leagues, every team's roster is used to identify unrostered players. For local sample teams, league ownership is unknown. During replay, imported ownership remains a current snapshot and must not be interpreted as historical availability.

## Scoring and data limitations

The original bonus-loss bug is fixed: double-double, triple-double, 40-point, and 50-point flags survive normalization. The configured bonuses stack. Confirm league semantics if using a new scoring format.

Flagrant-foul penalties are deliberately ignored by this model. Other missing rules, including technical-foul penalties, remain scoring gaps. The UI shows partial FP estimates and withholds lock decisions for those leagues. Data failures are alerts, not zero-game assumptions.

## Interview description

> I built a local NBA fantasy decision dashboard with read-only Sleeper roster synchronization, statistical lock/wait recommendations, and player improvement screening. A cached historical dataset makes analysis reproducible without repeated API calls. The system explicitly separates unavailable data from valid zero values and prevents future observations from entering replay calculations.

Discuss the independence assumption, missing scoring features, request cooldowns, and the distinction between a heuristic score and measured predictive accuracy. No performance improvement has yet been established through held-out evaluation.
