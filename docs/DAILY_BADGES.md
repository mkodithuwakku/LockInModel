# Previous-night player badges

Each refresh ranks the previous calendar day's observed NBA performances before
filtering to fantasy rosters. Box-score badges are identical across leagues;
fantasy-point badges use each league's own formula across the NBA player pool.

| Icon | Badge | Ranked stat |
| --- | --- | --- |
| 🎯 | Sniper | Made three-pointers (FG3M) |
| 🔥 | On fire | Made field goals (FGM) |
| 🐷 | Board hog | Rebounds |
| 🧱 | Bricklayer | Missed field goals (FGA − FGM); free throws excluded |
| 🥷 | Thief | Steals |
| 🚫 | Rejection | Blocks |
| 🏃 | Marathon man | Minutes played |
| 🪙 | Dropping dimes | Assists |
| 🥪 | Turnover sandwich | Turnovers |
| 🧾 | Free-throw merchant | Made free throws (FTM), not attempts |
| 💔 | Heartbreaker | Missed threes (FG3A − FG3M) |
| 🚀 | Above expectations | Largest positive actual FP − saved pregame projected FP |
| 🫠 | Below expectations | Largest shortfall below saved pregame projected FP |
| ⚡ | Minute maximizer | Highest fantasy points / minutes played |
| 🐌 | Slow night | Lowest fantasy points / minutes played |

Ranks use competition ranking: 1, 1, 3. Everyone in the first three places earns
the badge, including ties at third; this can mean more than three recipients.
Stat totals must be positive, but FP/min rankings include zero and negative fantasy
scores. Rates use total fantasy points divided by total minutes, excluding
zero-minute/DNP rows. There is no minimum-minutes threshold beyond positive
playing time: a short appearance can qualify. Exact ties use unrounded values.
Duplicate player/game records count once, with the last correction retained. Multiple games on a date are summed; the per-game forecast is multiplied by the number of observed games for that player-night.

Missing, imputed, nonfinite, or invalid category inputs suppress the category.
A performance-provider failure suppresses all badges. Yesterday's real results
are required; older observations and forecasts never become actual performances.
The fallback feed retains three-point attempts alongside makes so missed threes
are measured rather than inferred from total field-goal misses.

## Forecast comparisons

`forecast_store.py` maintains a `forecast_snapshots` table in the existing local
`data/lockin.sqlite3`, separate from the observed `games` table. No website database
or new scheduled job is needed. Each real live refresh builds forecasts for NBA
players on teams with a verified pregame matchup that day, including players
outside the user's rosters, using the same projection source precedence as the
roster. Work is shared by leagues with the same scoring formula.

Snapshots are keyed by scoring-formula fingerprint, game date, and player ID.
A later pregame refresh may replace an earlier estimate. In-progress, completed,
canceled, or unknown-status games do not create or update forecasts. Past dates
cannot be backfilled. At the next refresh, actual results are compared with the
saved forecast for that date and exact formula; changing scoring rules does not
reuse a forecast from different weights.

The above/below badges rank only players with both an observed result and a saved
pregame forecast. The detail label shows actual versus projected FP and forecast
coverage, such as `60/68 players with saved forecasts`. Missing forecasts are
excluded, never replaced by postgame estimates. These badges begin after the
archive has accumulated pregame snapshots; installing this feature cannot recover
forecasts that were never saved. Test Week has no fabricated forecast archive,
so it shows observational/rate badges but no saved-forecast comparison badges.

## Display

Roster rows show at most three 11–12px icons, ordered by rank then category, and a
small `+N` for extras. Hover for the stat/rank/date or tap the player to see all
badges. League-scored awards explicitly say `NBA · league scoring`. Badges do not
change points, lock decisions, projections, or recommended lineups.

The date follows the existing Edmonton report clock and NBA game dates. The
browser hides badges when they no longer represent yesterday, including after
midnight or waking an open tab. Expired/failed reports hide them too. Test Week
uses its simulated date. No games yesterday means no icons.

`daily_badges.py` computes stat rankings once per report and fantasy rankings once
per scoring formula. `pages.py` allowlists badge identity, rank, value, tie, scope,
and optional actual/projected FP and coverage. New raw-stat categories belong in
`CATEGORIES`; fantasy categories use `fantasy_night_badges()`. Icons and labels
live in `web/insights.js`.

The [expanded badge example](screenshots/expanded-badges-mobile.png) uses generic
team labels and real stored October 20 results. The earlier [desktop sample](screenshots/daily-badges-desktop.png)
and [phone sample](screenshots/daily-badges-mobile.png) use December 25, 2025
practice results and predate the new categories. None establishes model accuracy.
