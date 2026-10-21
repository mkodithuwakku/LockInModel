# Previous-night player badges

Each daily refresh ranks the previous calendar day's observed NBA performances
across the full player dataset, before filtering to fantasy rosters. The same
player receives the same badges in every league, regardless of scoring rules.

| Icon | Badge | Ranked stat |
| --- | --- | --- |
| 🎯 | Sniper | Made three-pointers (FG3M) |
| 🔥 | On fire | Made field goals (FGM), not attempts |
| 🐷 | Board hog | Rebounds |
| 🧱 | Bricklayer | Missed field goals (FGA − FGM); free throws excluded |
| 🥷 | Thief | Steals |
| 🚫 | Rejection | Blocks |
| 🏃 | Marathon man | Minutes played |
| 🪙 | Dropping dimes | Assists |
| 🥪 | Turnover sandwich | Turnovers |

Ranks use competition ranking: 1, 1, 3. Everyone in the first three places earns
the badge, including ties at third; this can mean more than three recipients.
Zero totals do not earn badges. Duplicated player/game records are counted once,
with the last correction retained. Multiple games on that date are summed.
Missing, imputed, nonfinite, or negative category measurements suppress that
category. A performance-provider failure suppresses all badges. No badges are
invented from projections, prior-season averages, or an older night's results.

Roster rows show at most three 11–12px icons, ordered by rank then category, and a
small `+N` for extras. Hover for the stat/rank/date or tap the player to see all
badges in the details sheet. They do not change fantasy points, lock decisions,
projections, or recommended lineups.

The daily date follows the existing Edmonton report clock and NBA game dates.
The browser hides badges when they no longer represent yesterday, including after
midnight or waking an open tab. An expired/failed published report hides them too.
Test Week uses its simulated date, so badges only describe the preceding day;
advancing to night never reveals a future badge. No games yesterday means no icons.

`daily_badges.py` computes ranks once per report from the existing game logs; no
new provider requests, database, or scheduled job is added. The engine attaches
`daily_badges` to roster results, and the static exporter allowlists only
`key`, `date`, `rank`, `value`, and `tied`. Add a new stat definition in
`CATEGORIES` and its icon/label in `web/insights.js` to extend the categories.

The [desktop sample](screenshots/daily-badges-desktop.png) and
[phone sample](screenshots/daily-badges-mobile.png) use a generic practice roster
and observed December 25, 2025 results. They are not current NBA recommendations.
