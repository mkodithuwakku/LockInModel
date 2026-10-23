# Per-game projections

Every roster player has a projection independently of start eligibility. Bench, injury, and off-day status affect the recommended lineup, not the display of expected production when active.

## Sources and precedence

1. Current-season observations strictly before the target day, rescored with the league formula. While a player has fewer than `decision.lookback_games` current-season games (default 10), the latest available prior-season games fill the window. Newer games carry more weight. At 10 current-season games, projections use the normal current-season recency/shrinkage model.
2. A validated current-season **Sleeper / RotoWire** forecast when current observations are unavailable. The live refresh requests `https://api.sleeper.com/projections/nba/<season>?season_type=regular&grouping=season` through the existing paced HTTP cache (six hours). Replay never uses this source.
3. Saved historical observations, with explicit prior-season provenance, if a current forecast is absent. The previous season is read from SQLite or checksum-verified fixtures; older fixture priors cover players who missed that season.

Unusable records remain unavailable with an explanation. They never become invented zero forecasts. Rookie identity can use Sleeper's imported player ID; it does not require an invented NBA ID.

## Opponent-aware overlay (`opponent_ridge`)

After the baseline above is chosen, `lineup.apply_opponent_model()` scores every unplayed `week_games` tile for players with a confirmed opponent and at least five prior observations. `features.FeatureBuilder` builds strictly pregame context — Dean Oliver possessions/pace, rolling 15-game opponent defensive rating and per-100-possession concessions, positional concession ratios, rest and home flags — and `model_ml.ComponentRidge` predicts each box-score component (PTS/REB/AST/STL/BLK/TOV/FG3M). Rest counts scheduled-but-unplayed games, so a Friday tile sees Wednesday's game. The components overlay the baseline's full stat line and are rescored through `scoring.add_fantasy_points()`, so any league formula and milestone bonuses apply unchanged. Each tile carries the per-game result as `proj_fp` (Wednesday vs. Charlotte and Friday vs. Boston show distinct values); the tile for the reference date also replaces the player's profile, labeled `projection_source: "opponent_ridge"`. Training uses only games strictly before the target date, and any failure — sparse history, unconfirmed opponent, missing scoring inputs, or a fit error — keeps the baseline estimate untouched. The challenger measured lower paired game MAE and weekly regret than the baseline policy on the 2024-25/2025-26 fixtures before promotion; retrospective results are not prospective guarantees.

The overlay's hyperparameters — Ridge `lam`, rolling feature window, player-form decay/lookback, and the minimum-history gates — live in the `model:` section of `config.yaml` (defaults shown there; `model_ml.model_settings(cfg)` resolves them for production and the evaluator alike). The model refits nightly on the latest games, but nothing tunes these values automatically: `evaluator.py --mode tune` ranks a λ×window×decay grid by walk-forward game MAE and prints a ready-to-paste config block; `--mode game`/`--mode weekly` against the live database give prospective scorecards. See the biweekly model-check workflow in `docs/agents/WORKFLOWS_AND_TESTING.md`.

The projection carries source, as-of date, FP, stat components, and either observed sample/last-played metadata or the forecast provider update time. The public export allowlists every nested field. Forecasts are cached separately from observed games and never inserted as completed games. Real live refreshes also archive same-day pregame estimates for the NBA player pool in a separate table in the existing SQLite database, so next-day [above/below-projection badges](DAILY_BADGES.md#forecast-comparisons) use a saved benchmark.

## Small current-season samples

A player with one current-season game uses that game plus up to nine latest prior-season games; the second game replaces one old game, and so on. This is based on each player's observed game count, not the calendar date, so it also covers a player returning from injury midseason. With no usable prior history, only actual available games are used. No games are invented to fill the window.

The blend uses the existing exponential decay (default 0.92), includes older games despite the 14-day recent filter, and does not add the same history again as a shrinkage prior. Both fantasy points and projected components use this window. Player details show the current/prior counts. These estimates also feed the exact daily lineup optimizer and upcoming weekly tiles.

The same observed-history blend supports weekly lock baselines and rarity comparisons. It never turns an older performance into a lock candidate; a completed game in the current fantasy week and a verified remaining schedule are still required. The latest performance participates in the ordinary performance baseline but is excluded from rarity comparisons. Returning from injury does not imply a known minutes restriction or role adjustment; this remains a heuristic.

## Projected scoring

The Sleeper response identifies its season, regular-season scope, projection category, RotoWire provider, and season grouping. Required values must be finite and nonnegative. Stats are divided by `gp` for per-game values; `sp` becomes minutes, and OREB can be derived from REB minus DREB. Existing foul omissions and total-rebound fallback apply when the corresponding projected inputs are absent. Every league's scoring weights are then applied separately.

For observed history, projected FP is the weighted mean of **game-level fantasy scores**, so milestone bonuses retain their observed frequencies. Stat components use the same recency and prior weights. Rounded displayed components need not reconstruct the displayed FP exactly.

For external forecasts, ordinary components are linear weighted expectations. Supplied DD/TD frequencies are used directly. A mean stat line must not be treated as a completed game: averaging 9.9 rebounds does not imply a zero chance of reaching ten. When a required milestone frequency is absent, the app estimates `P(Poisson(projected stat mean) >= threshold)`. Missing DD/TD frequencies use independent Poisson category probabilities for PTS/REB/AST/STL/BLK. This is an explicit approximation, not a calibrated probability model. Notes appear under Scoring method rather than operational alerts.

## Display and availability

Roster rows show projected FP and PTS/REB/AST; player details add minutes, steals, blocks, turnovers, threes, and shooting makes/attempts. Sources and dates remain visible. Each upcoming or in-progress game tile in the seven-day strip displays the saved per-game FP baseline as **Proj**. The baseline is repeated across matchups; it is not an opponent-specific prediction. Completed games show observed **Final** FP when available, including zero or negative scores. Missing forecasts or final scores stay as dashes; postponed/canceled games carry their status without a forecast. Current forecasts are never backfilled into games before their as-of date. Current-season history-based values supersede forecast fallback once usable observations exist. During a game-log failure only independently valid external forecasts can support the daily plan; weekly lock/pickup decisions still need observed data.

Historical charts remain observed-only. Verified older observations are shown with a prior-season label when current history is absent. A rookie may have a complete forecast and no NBA history chart. This is an honest absence of observations, not a broken forecast.

The roster sheet uses the latest saved daily assignment and retains its original date until a new refresh replaces it, including across midnight. Per-game estimates remain dated baseline information in a saved report; they are not live availability or permission to start a player. The Mac's existing scheduled publication carries new forecasts to GitHub Pages without adding a database there.

## Proposed opponent-aware extension

The [opponent-aware projection epic](epics/OPPONENT_AWARE_PROJECTIONS.md) plans
separate forecasts for each player/game, using opportunity estimates and
player-style/opponent interactions before league scoring. It covers additional
data sources, reproducible pregame snapshots, sparse-history treatment,
validation, fallbacks, and later lock-model integration. **This is not implemented:**
current weekly tiles still repeat the saved per-player baseline described above.
No model or refresh behavior changes with the proposal.
