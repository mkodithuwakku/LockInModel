# Scoring and model reference

This describes the implemented behavior in `fetch_data.py`, `scoring.py`, `decide.py`, and `model.py`. Examples are synthetic. No historical performance is implied.

## 1. Fantasy scoring

For each game:

```text
FP = Σ (stat value × configured stat weight)
```

The current base scoring is:

```text
FP = 0.5·PTS + REB + AST + 2·STL + 2·BLK − TOV + 0.5·FG3M
```

`FGM`, `FGA`, `FTM`, and `FTA` are present but have zero weight. Missing weighted columns are filled with zero by `add_fantasy_points()`. Existing NaNs can propagate and invalid strings can fail conversion.

### Derived bonuses

`_compute_derived_flags()` implements these indicators:

| Flag | Condition | Configured FP |
| --- | --- | --- |
| `DD` | At least two of PTS, REB, AST, STL, BLK reach 10 | 1 |
| `TD` | At least three of those categories reach 10 | 2 |
| `PTS40` | PTS ≥ 40 | 2 |
| `PTS50` | PTS ≥ 50 | 2 |

The conditions stack: a triple-double qualifies for DD and TD, and a 50-point game qualifies for PTS40 and PTS50. Confirm that this matches the intended league rules before preserving it in a fix.

The normalizer retains the derived flags and identifiers. The main pipeline scores these bonuses and makes them available to the rarity calculation.

For a synthetic game with 50 PTS, 10 REB, 10 AST, 2 STL, 1 BLK, 3 TOV, and 4 FG3M:

```text
Base FP = 25 + 10 + 10 + 4 + 2 − 3 + 2 = 50
Intended bonuses = DD 1 + TD 2 + PTS40 2 + PTS50 2 = 7
Current pipeline output = 57 FP
```

The dataset does not supply technical or flagrant fouls. By explicit user policy, flagrant-foul scoring (`ff`) is omitted from every model decision, baseline, and pickup calculation. The original penalty is retained as `ignored_scoring` metadata, not an error. Other unsupported rules, including technical fouls (`tf`), still cause partial FP and withheld recommendations.

## 2. Selecting the candidate and baseline

The pipeline sorts game logs chronologically, filters the selected Monday–Sunday week, and selects its last row as the candidate. There must be at least one game this week to produce a decision.

The baseline first takes games within `recent_days` of the decision date, then the final `lookback_games` rows. With the checked config this means **up to 10 games within 14 days**. It does not automatically expand to 10 games when only five exist in that 14-day window. Only when the recent-days subset is entirely empty does it fall back to the final `lookback_games` rows of all available logs, themselves limited by the initial 60-day filter.

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

This shrinkage applies whenever its conditions hold, not only at the start of a season. With at most 10 selected games and 12 pseudo-games, the prior can dominate the mean throughout the year. The mixing weight uses raw row count rather than effective weighted sample size.

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

Assume future scores are independent draws from the same `Normal(μ, σ)` distribution. For candidate score `c` and `n` remaining games:

```text
z = (c − μ) / σ
P(one future score ≤ c) = Φ(z)
P(all n future scores ≤ c) = Φ(z)^n
P(at least one future score > c) = 1 − Φ(z)^n
initial p_lock = Φ(z)^n
```

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

## 9. Assumptions to evaluate

- Normal scores, independence between games, and an unchanged player role over remaining games.
- The schedule count is accurate and scheduled games translate into player appearances.
- Career averages are a useful anchor for the current role and scoring system.
- The latest completed score is still eligible to lock under league rules.
- Rarity and preference adjustments improve decisions rather than just confidence.

There are no injury, opponent, minutes-projection, home/away, or back-to-back features. See the [replay proposal](HISTORICAL_REPLAY.md) for how to evaluate the policy without exposing future results to it.

## 10. Player improvement screening

`pickups.py` uses five recent observed games and a disjoint baseline of eight to twenty earlier games, within 90 days. Recent means use exponential decay 0.92. Candidates require at least 4 FP improvement, at least 0.5 baseline SD improvement, 60% of recent games above baseline, 18 recent minutes per game, and an appearance within seven days.

The estimated future FP is:

```text
baseline + improvement × consistency × sustainability × 0.7
```

Sustainability begins at 1 if minutes rose by at least two, otherwise 0.6. An effective-shooting increase above 0.12 multiplies it by 0.7; a steals-plus-blocks increase above 1.5 multiplies it by 0.75. These are explicit heuristics that need evaluation.

The ranking score combines standardized FP improvement, minutes improvement, and consistency, clipped to 0–100. It is not a probability. Team fit compares the candidate projection with a compatible roster alternative, preferring bench players. Available ownership data excludes every rostered player, including reserves/taxi players. Without full league ownership, availability is labeled unknown.

Email pickup alerts require complete scoring, known ownership, and positive estimated fit. They are deduplicated for 72 hours unless the signal increases materially. No player acquisition is submitted automatically.
