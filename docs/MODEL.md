# Scoring and model reference

This describes the implemented behavior in `fetch_data.py`, `scoring.py`, `decide.py`, and `model.py`. Examples are synthetic. No historical performance is implied.

## 1. Fantasy scoring

For each game:

```text
FP = Σ (stat value × configured stat weight)
```

The sample configuration's base scoring is (imported leagues use their own weights):

```text
FP = 0.5·PTS + REB + AST + 2·STL + 2·BLK − TOV + 0.5·FG3M
```

`FGM`, `FGA`, `FTM`, and `FTA` have zero weight in the sample configuration. The normalizer tracks absent optional stats as imputed. `add_fantasy_points()` rejects missing required weighted columns and non-finite values. The explicit foul/rebound policy below allows approximations for those optional fields.

### Derived bonuses

The sample configuration enables these indicators. The normalizer retains traditional flags, while `add_fantasy_points()` recomputes active bonuses from base observations rather than trusting saved flags:

| Flag | Condition | Configured FP |
| --- | --- | --- |
| `DD` | At least two of PTS, REB, AST, STL, BLK reach 10 | 1 |
| `TD` | At least three of those categories reach 10 | 2 |
| `PTS40` | PTS ≥ 40 | 2 |
| `PTS50` | PTS ≥ 50 | 2 |

The conditions stack: a triple-double qualifies for DD and TD, and a 50-point game qualifies for PTS40 and PTS50. Each qualifying threshold contributes its configured weight once. There is no exclusive-tier bonus mode.

The normalizer retains the traditional derived flags and identifiers. Scoring recomputes indicators from base observations, including generic thresholds such as `AST15` (15+ assists) and `REB20` (20+ rebounds); a new league can add a positive PTS/REB/AST/STL/BLK threshold without changing Python code.

For example, `AST15: 3` adds 3 FP at 15 assists and `REB20: 5` adds 5 FP at 20 rebounds. Below-threshold observations add zero; reaching both adds 8 FP on top of the other configured terms. The sample defaults set these two weights to zero. Imported Sleeper milestones and older saved unsupported milestone entries map into the same generic formula; see [Configuration](CONFIGURATION.md).

For a synthetic game with 50 PTS, 10 REB, 10 AST, 2 STL, 1 BLK, 3 TOV, and 4 FG3M:

```text
Base FP = 25 + 10 + 10 + 4 + 2 − 3 + 2 = 50
Intended bonuses = DD 1 + TD 2 + PTS40 2 + PTS50 2 = 7
Current pipeline output = 57 FP
```

Technical and flagrant foul penalties (`tf`, `ff`) are omitted and retained in `ignored_scoring` metadata. Personal fouls (`PF`) use actual values when available and are omitted otherwise. Offensive/defensive rebound weights use actual splits when available; otherwise the model uses total rebounds with coefficient `REB weight + (OREB weight + DREB weight) / 2`, treating an absent split weight as zero. Equal split weights are exact; unequal weights are an approximation. These approved adjustments are shown as information and do not block recommendations. Other unknown nonzero rules still withhold actionable recommendations.

## 2. Selecting the candidate and baseline

The dashboard's **Recent form** panel is descriptive and does not change this model. Its average is the arithmetic mean of up to five latest valid scored observations through the report cutoff. Its delta compares that mean with the preceding five observations only when both complete windows exist. These values differ from the recency-weighted, prior-adjusted baseline below. Each sparkline uses its own score range, with the oldest observation on the left; its height is not a shared scale across players. Missing comparisons display a dash, including when only nine games exist.

The pipeline sorts game logs chronologically, filters the selected Monday–Sunday week, and selects its last row as the candidate. There must be at least one game this week to produce a decision.

When fewer than `lookback_games` current-season games exist, the baseline fills the window with the latest available prior-season games, using the same league formula and decay. At the default of 10, one current game plus nine prior games gradually becomes ten current games. This is per player, including midseason injury returns. No extra mean-shrinkage prior is applied during that blend. With no usable prior games, the original sparse-sample guards remain.

Outside that bootstrap, the baseline first takes games within `recent_days` of the decision date, then the final `lookback_games` rows. With the checked config this means **up to 10 games within 14 days**. It does not automatically expand to 10 games when only five exist in that window. Only when the recent-days subset is entirely empty does it fall back to the final `lookback_games` rows of available observations. The decision helper bounds those observations to 3,650 days through the reference date; the provider may supply a shorter history.

The FP baseline **includes the candidate game**. The rarity baseline excludes the final selected row. Including a just-completed game is a valid design choice for forecasting later games, but it should remain explicit during evaluation. The shared engine and decision helper filter future observations before inference.

## 3. Weighted recent mean and standard deviation

For `m` selected rows in oldest-to-newest order, score `xᵢ`, and decay `d`:

```text
wᵢ = d^(m − 1 − i), where i = 0, …, m − 1
μ_recent = Σ(wᵢ xᵢ) / Σwᵢ
σ_recent² = Σ(wᵢ (xᵢ − μ_recent)²) / Σwᵢ
```

The newest weight is 1.0. At the default `d = 0.92`, the weights of the last three rows are `0.8464, 0.92, 1.0`. This uses a weighted population variance, not a sample correction. Non-finite scores and nonpositive/non-finite weights are removed by `_weighted_mean_std()`; `sample_size` still counts selected rows.

## 4. Career mean shrinkage

The mean formula accepts any explicitly identified longer-term prior. Fixture replay uses 2024–25 game averages scored with the same supported weights, including bonuses. Live analysis uses older observed season-to-date games, before the recent 14-day window, to avoid per-player career requests. The legacy `compute_career_fp()` adapter remains available but is not the main provider’s prior policy. A prior-season average must not be described as a career average.

With finite career prior `μ_career`, `m > 0`, and positive prior weight `k`:

```text
μ = (m·μ_recent + k·μ_career) / (m + k)
```

With five recent games averaging 40 FP and a 30-FP career prior, `k = 12` gives:

```text
μ = (5·40 + 12·30) / 17 ≈ 32.94 FP
```

This shrinkage applies when its conditions hold outside the explicit current/prior-game bootstrap. With at most 10 selected games and 12 pseudo-games, the prior can dominate the mean throughout the year. The mixing weight uses raw row count rather than effective weighted sample size.

If the prior is missing, the recent mean is used. A finite zero prior still participates in shrinkage; zero is treated specially only for the variance guard. With no selected rows, the baseline mean falls back to the prior, although the normal main path returns earlier when there are no usable logs.

## 5. Small-sample variance guard

The configured guard is:

```text
guard = rookie_guard_fp                              if prior is missing or zero
guard = max(sd_floor_min, career_guard_scale·prior)   otherwise
```

Defaults are `17.5`, `4.0`, and `0.6`, respectively. The final SD is:

```text
σ = max(usable recent SD or 0, guard)   if recent SD is non-finite or m < 3
σ = max(recent SD, sd_floor_min)       otherwise
```

The larger prior/rookie guard applies to tiny samples. The configured absolute minimum SD now also applies to histories of three or more games, preventing identical histories from implying near-certainty.

## 6. Probability of a better future game

Assume future scores are independent draws from `Normal(μ_i, σ)` where each remaining game `i` has its own mean. For candidate score `c` and `n` remaining games:

```text
P(game i ≤ c) = Φ((c − μ_i) / σ)
P(all n future scores ≤ c) = Π_i Φ((c − μ_i) / σ)
P(at least one future score > c) = 1 − Π_i Φ((c − μ_i) / σ)
initial p_lock = Π_i Φ((c − μ_i) / σ)
```

When the engine has opponent-aware Ridge tiles for the player's remaining games, `future_mus` supplies those per-game means (μ_i = the tile projection, including rest and venue); games without a ridge value and any length mismatch fall back to the uniform baseline mean `μ`. Without `future_mus` the model degenerates to `Φ(z)^n` as before.

Special cases in `probability_future_beats_current()`:

| Condition | Returned probability of a future score beating current |
| --- | --- |
| `n ≤ 0` | 0 |
| Non-finite mean or SD | `1 − 0.5^n` |
| SD ≤ `1e-6` | 1 if mean > current; otherwise 0 |
| Otherwise | Normal formula, clipped to [0, 1] |

The comparison is strictly greater, so ties do not count as improvements. Non-finite candidate scores are not independently rejected.

## 7. Rarity

The rarity columns are the configured `rare_stats` plus `DD`, `TD`, `PTS50`, and `PTS40`, deduplicated. For each column, the code calculates an unweighted previous-game mean and sample SD (`ddof=1`). Rarity requires at least three previous observations and positive variance; unusable SD values remain missing and are skipped.

For a usable stat with current value `v`:

```text
z_stat = (v − mean_previous) / sd_previous
Keep z_stat if it is at least rare_z_threshold
rarity = 1 − exp(−0.5 · Σ min(3, z_stat))
```

No qualifying stats gives rarity zero. A z-score is capped at 3 per stat. A single capped contribution yields approximately 0.777 rarity, adding about 0.117 with the default bias. Constant or insufficient history does not create a rarity boost.

## 8. Decision adjustments

Starting from `1 − P(future beats current)`, apply these in order:

| Rule | Change to `p_lock` |
| --- | --- |
| Rarity | Add `rarity × lock_bias_if_rare` (default 0.15) |
| Fewer than 3 baseline rows and at least 1 remaining game | Subtract 0.10 |
| At least 2 remaining games | Subtract `min_remaining_games_bias` (default 0.05) |
| `conservative_mode: true` | Add 0.05 |

Then clip to [0, 1], set `p_wait = 1 − p_lock`, and choose LOCK at `p_lock ≥ 0.5`.

These are hand-tuned preferences. The probability of a future improvement is also different from the expected points obtained by a sequential locking policy: the model does not calculate how much better or worse future games might be or solve an optimal stopping problem.

## 9. Roster and slot contention (Stage 2)

The solo probability above values a score only against the same player's remaining games. `decide.apply_roster_lock_context(team, rows, locks)` then re-weights each decided row against the rest of the roster, because a locked score permanently occupies one of the league's active slots (`active_slots(team)` minus slots already pinned by `state/locks.json` records or Test Week `banked` scores).

For every unpinned, non-reserve (`IR`/`TAXI`), healthy teammate `j`, a weekly contender distribution is built: any already-scored `last_game_fp` plus a projected mean per remaining game (`week_games` tile `proj_fp`, else `projection.projected_fp`, else `fp_mean_recent`) with `σ_j = max(fp_std_recent, 4)`. Numerical quadrature over the independent-normal product CDF yields the expected weekly ceiling `E[M_j]`; `P(M_j ≤ c) = 1(c_j ≤ c) · Π_m Φ((c − μ_{j,m}) / σ_j)`.

For each candidate `i` with a completed score, the code finds the distinct open slot names the player is eligible for. If none exists, the row is forced to WAIT with an "already pinned" explanation. Otherwise `optimal_assignment()` (the same Hungarian solver as the daily lineup) seats all other contenders across the open slots; removing one instance of each eligible slot name and re-solving finds the slot that maximizes the others' total — and the contender `j*` seated in the baseline but not in the reduced assignment (the marginal displaced starter). The team-aware probability is `p_lock,team(i) = p_lock,solo(i) × P(M_j* ≤ c_i)`; when no contender is displaced (an uncontested open slot), the factor is 1 and the solo decision stands. The solo score is preserved as `p_lock_solo`/`decision_solo`, so the pass is idempotent and reversible.

Explanations surface only inside `row["reason"]` (the player modal): a contested WAIT names the displaced contender, their projected weekly ceiling, remaining games, and the contested slot; a cleared LOCK names the beaten contender. Quick-view roster cards are unchanged.

## 10. Assumptions to evaluate

- Normal scores, independence between games, and an unchanged player role over remaining games.
- The schedule count is accurate and scheduled games translate into player appearances.
- Career averages are a useful anchor for the current role and scoring system.
- The latest completed score is still eligible to lock under league rules.
- Rarity and preference adjustments improve decisions rather than just confidence.

There are no injury, opponent, minutes-projection, home/away, or back-to-back features. See the [historical replay guide](HISTORICAL_REPLAY.md) for how to evaluate the policy without exposing future results to it.

## 11. Player improvement screening

The On the rise directory is independent of trend qualification: verified unrostered players remain browsable without history, using empty analysis placeholders. The directory itself is not a recommendation.

`pickups.py` uses five recent observed games and a disjoint baseline of eight to twenty earlier games, within 90 days. Recent means use exponential decay 0.92. Candidates require at least 4 FP improvement, at least 0.5 baseline SD improvement, 60% of recent games above baseline, 18 recent minutes per game, and an appearance within seven days.

The estimated future FP is:

```text
baseline + improvement × consistency × sustainability × 0.7
```

Sustainability begins at 1 if minutes rose by at least two, otherwise 0.6. An effective-shooting increase above 0.12 multiplies it by 0.7; a steals-plus-blocks increase above 1.5 multiplies it by 0.75. These are explicit heuristics that need evaluation.

The ranking score combines standardized FP improvement, minutes improvement, and consistency, clipped to 0–100. It is not a probability. Team fit compares the candidate projection with a compatible roster alternative, preferring bench players. Available ownership data excludes every rostered player, including reserves/taxi players. Without full league ownership, availability is labeled unknown.

Email pickup alerts require complete scoring, known ownership, and positive estimated fit. They are deduplicated for 72 hours unless the signal increases materially. No player acquisition is submitted automatically.

## 12. Daily lineup projections and assignment

`lineup.project_players()` filters both current and fallback observations to `GAME_DATE < target date`, even in night replay. Each league's original effective scoring policy is applied to those box scores, including derived bonuses and the approved foul/rebound approximations. While there are fewer than `lookback_games` current-season observations (default 10), `season_history.blend_seasons()` fills the window with the latest available prior-season games. The same helper supplies weekly lock baselines, including for a midseason injury return with few appearances. The combined window bypasses `recent_days` and has no additional mean-shrinkage prior, so old games are not counted twice. Actual sample counts remain explicit if historical coverage is sparse. At the target count, the normal model takes up to `lookback_games` from `recent_days`, or the latest available current-season games if that window is empty. `rolling_baseline()` supplies the recency-weighted mean (default decay 0.92); when recent games exist, older current-source observations supply the shrinkage prior with the configured pseudo-game weight. Values are rounded to 0.01 FP for assignment.

Current-season or blended history takes precedence per player. Historical performances cannot become this week’s lock candidates; the weekly decision still selects its latest score from current observations only. Its rarity reference excludes that latest score, while the ordinary performance baseline includes it. In live mode, missing usable current history falls back first to the current-season Sleeper / RotoWire per-game forecast, then saved historical observations. Historical fallback reads the prior season from SQLite or a checksum-verified fixture, and the fixture prior table for players who missed that season. Replay uses only its verified historical inputs and never fetches current forecasts. Each estimate carries its source, projected stat components, as-of date, and either sample/last-played information or forecast update time. Missing history and forecasts yield unavailable values, not zero. [Forecast scoring and bonus assumptions](PROJECTIONS.md) are distinct from observed-game scoring; no predictive accuracy is established.

For players with confirmed opponents and at least five prior league observations, `lineup.apply_opponent_model()` scores every unplayed `week_games` tile with an opponent-aware forecast: a `ComponentRidge` model trained on strictly-prior league games predicts each stat component over `FeatureBuilder` pregame context (pace, opponent defensive and positional concessions, rest/home with scheduled unplayed games counting toward rest), components merge over the baseline's full box estimate, and the league formula rescores each tile as `proj_fp`. The tile for the target date also replaces the primary baseline profile as `projection_source: "opponent_ridge"`. Sparse history, unconfirmed opponents, or any model error keep the baseline profile — the fallback is the unadjusted estimate, never a zero. Hyperparameters are resolved via `model_ml.model_settings(cfg)` and configurable under `model:` in YAML.

`recommend_lineup()` considers the full roster including bench players, but excludes IR/taxi and confirmed-out/inactive/suspended players. Live injuries use the imported snapshot; questionable/DTD players remain eligible with their label. A verified game on the target date is required to score in the plan. Live games already started/finished are excluded; replay treats the day as a pregame planning exercise and never looks at that day's box-score values. Historical availability is not known.

The complete imported `roster_positions` list defines the active slots. PG/SG/SF/PF/C require that position, G accepts PG/SG, F accepts SF/PF, and UTIL accepts any roster player. BN/IR/TAXI are not active slots. Duplicate and empty active slots remain in the assignment. Local practice teams without an explicit layout use one UTIL per starter; an imported team without a layout must sync again rather than guessing.

The rectangular Hungarian solver maximizes the sum of projections with one player per eligible slot and at most one slot per player. Zero-value dummy assignments represent vacancies; negative-value players need not be started. Time is `O(S² × (P + S))`. Unit tests compare its result with independent exhaustive enumeration, including flexible-position conflicts. This guarantees the maximum **for the supplied eligible candidates and projections**, not maximum realized points. Missing inputs produce `partial`, no available games produces `no_games`, and unsupported slots/scoring or provider failures produce `unavailable`.

When the eligible pool leaves slots vacant — typically a quiet or game-free day — the sheet fills the leftover slots with healthy benched players who cannot start right now: no game today, a started or finished game, an unconfirmed schedule, or a missing projection. Placeholders are marked `off_day`, add zero projected FP, and never displace an eligible starter or duplicate a player. Reserve, out/injured, and actively-playing benched candidates never hold a slot. Locked players pin to their synced slot even without a game that day. This is a roster-display fallback layered on the optimal assignment, not a change to the solver's eligibility.

Weekly Sleeper locks and Game Pick selections are not imported. This plan therefore assumes positions can be rearranged before games and is not a legal-move validator. Sleeper documents [position restrictions after locking](https://support.sleeper.com/en/articles/6522833-lock-in-mode-details); users must check existing locks and deadlines there. Known banked Test Week scores suppress the unrestricted preview until restart. The dated daily assignment remains displayed until the next report replaces it; it is not recomputed or erased at midnight. Older snapshots are labeled with their original date and report freshness.

### Live final-game observations

Live reports accept same-day box scores only when the schedule confirms a final. If NBA Stats is unavailable or missing recent finals, validated Sleeper / Sportradar game rows enter the same SQLite store and scoring path. The fallback verifies team scoring totals and playing-time coverage, and never uses season aggregates or projections as observations. Opening-night finals are eligible immediately on an explicit refresh. Historical replay retains its separate morning/night cutoffs.
