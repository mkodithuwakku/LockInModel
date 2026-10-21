# Per-game projections

Every roster player has a projection independently of start eligibility. Bench, injury, and off-day status affect the recommended lineup, not the display of expected production when active.

## Sources and precedence

1. Current-season observations strictly before the target day, rescored with the league formula and weighted using the configured recency/shrinkage model.
2. A validated current-season **Sleeper / RotoWire** forecast when current observations are unavailable. The live refresh requests `https://api.sleeper.com/projections/nba/<season>?season_type=regular&grouping=season` through the existing paced HTTP cache (six hours). Replay never uses this source.
3. Saved historical observations, with explicit prior-season provenance, if a current forecast is absent. The previous season is read from SQLite or checksum-verified fixtures; older fixture priors cover players who missed that season.

Unusable records remain unavailable with an explanation. They never become invented zero forecasts. Rookie identity can use Sleeper's imported player ID; it does not require an invented NBA ID.

The projection carries source, as-of date, FP, stat components, and either observed sample/last-played metadata or the forecast provider update time. The public export allowlists every nested field. Forecasts are cached separately from immutable observations and never inserted as completed games.

## Projected scoring

The Sleeper response identifies its season, regular-season scope, projection category, RotoWire provider, and season grouping. Required values must be finite and nonnegative. Stats are divided by `gp` for per-game values; `sp` becomes minutes, and OREB can be derived from REB minus DREB. Existing foul omissions and total-rebound fallback apply when the corresponding projected inputs are absent. Every league's scoring weights are then applied separately.

For observed history, projected FP is the weighted mean of **game-level fantasy scores**, so milestone bonuses retain their observed frequencies. Stat components use the same recency and prior weights. Rounded displayed components need not reconstruct the displayed FP exactly.

For external forecasts, ordinary components are linear weighted expectations. Supplied DD/TD frequencies are used directly. A mean stat line must not be treated as a completed game: averaging 9.9 rebounds does not imply a zero chance of reaching ten. When a required milestone frequency is absent, the app estimates `P(Poisson(projected stat mean) >= threshold)`. Missing DD/TD frequencies use independent Poisson category probabilities for PTS/REB/AST/STL/BLK. This is an explicit approximation, not a calibrated probability model. Notes appear under Scoring method rather than operational alerts.

## Display and availability

Roster rows show projected FP and PTS/REB/AST; player details add minutes, steals, blocks, turnovers, threes, and shooting makes/attempts. Sources and dates remain visible. Current-season history-based values supersede forecast fallback once usable observations exist. During a game-log failure only independently valid external forecasts can support the daily plan; weekly lock/pickup decisions still need observed data.

Historical charts remain observed-only. Verified older observations are shown with a prior-season label when current history is absent. A rookie may have a complete forecast and no NBA history chart. This is an honest absence of observations, not a broken forecast.

The daily lineup's midnight expiry is unchanged. Per-game estimates remain dated baseline information in a saved report; they are not live availability or permission to start a player. The Mac's existing scheduled publication carries new forecasts to GitHub Pages without adding a database there.
