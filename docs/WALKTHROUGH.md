# Relearning LockIn

## The decision you built it for

A player may play several times during a fantasy week, but only one chosen performance counts in a lock-in format. The application evaluates whether the latest completed score is worth keeping or whether remaining opportunities justify waiting.

It does not submit the decision to Sleeper. It also does not infer that you have already locked a player: existing lock selections are not imported.

## Daily workflow

Open the dashboard and choose a team. The roster shows the latest score, recent baseline, remaining opportunities, and a decision status. Open a player to inspect actual observed game history and the explanation behind the recommendation.

Mint indicates LOCK and lavender indicates WAIT. Amber indicates a review requirement, such as an unavailable schedule or incomplete scoring. A lock score is a heuristic preference; it is not calibrated confidence.

Local sample rosters can be edited in **Edit roster**. A checkbox moves a player between starters and bench; adding or removing a player changes the canonical local YAML. The email report reads that same file. Sleeper rosters are managed in Sleeper and refreshed using the connection dialog.

## Replay versus live

Historical replay opens a saved week from December 22–28, 2025. The selected date means the end of that league day. A Thursday view knows Thursday's completed performances but cannot use Friday's outcomes. The full season remains stored locally so changing dates never requires another NBA fetch.

Live analysis is an explicit refresh. It uses completed observations through the previous day for a noon report, counts remaining schedule opportunities, and labels unavailable data. Merely opening the dashboard does not start NBA retrieval. Saved live reports become stale after six hours or a date change, at which point lock recommendations are withheld until refreshed.

All imported leagues are currently completed offseason leagues. Live processing recognizes that condition and can stop without NBA calls; local historical teams remain useful for testing.

## How the lock model reasons

Suppose a player usually produces 35 FP with a 10-FP standard deviation and just scored 45. The Normal model estimates a 15.9% chance that one future game exceeds 45. With one game left, the initial lock probability is 84.1%; with three left, it is approximately `0.8413³ = 59.6%`.

More opportunities make waiting more attractive. The application then adjusts for rarity, sample size, and configured preferences. This is an explicit statistical rule, not a trained machine-learning model or an optimal-stopping solver.

## How the pickup finder reasons

A single outstanding performance can be a good score to lock without indicating that the player is a good long-term pickup. The finder compares the last five observed games against a separate earlier window of up to 20 games.

It asks whether FP increased, whether minutes increased, how consistently the player exceeded their baseline, and whether unusually strong shooting or steals/blocks account for the improvement. An estimated projection is compared with a position-compatible roster alternative, preferring bench players when available.

For imported leagues, every team's roster is used to identify unrostered players. For local sample teams, league ownership is unknown. During replay, imported ownership remains a current snapshot and must not be interpreted as historical availability.

## Scoring and data limitations

The original bonus-loss bug is fixed: double-double, triple-double, 40-point, and 50-point flags survive normalization. The configured bonuses stack. Confirm league semantics if using a new scoring format.

Some imported leagues use technical/flagrant foul penalties unavailable in the saved tables. The UI shows partial FP estimates and withholds lock decisions for those leagues. Data failures are alerts, not zero-game assumptions.

## Interview description

> I built a local NBA fantasy decision dashboard with read-only Sleeper roster synchronization, statistical lock/wait recommendations, and player improvement screening. A cached historical dataset makes analysis reproducible without repeated API calls. The system explicitly separates unavailable data from valid zero values and prevents future observations from entering replay calculations.

Discuss the independence assumption, missing scoring features, request cooldowns, and the distinction between a heuristic score and measured predictive accuracy. No performance improvement has yet been established through held-out evaluation.
