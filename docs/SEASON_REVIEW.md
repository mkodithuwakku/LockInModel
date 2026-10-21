# Season review

Open **Season review** to see every published team's season production, then
select a team card for its breakdown. The default **My teams** view still opens
on the recommended roster sheet.

## What the numbers mean

This is the **current roster's observed NBA production**, scored under that
league's formula. It includes games played before a player joined this roster.
It is not Sleeper's weekly locked scores, standings, or historical team ownership.
A dropped player's season production leaves the review at the next roster sync;
an added player's observed season games enter it. No transaction history is
invented. Teams with different formulas are not ranked against one another.

- **Roster FP:** sum of observed fantasy points for current roster players.
- **FP / appearance:** total FP divided by player-game appearances, not NBA team
  games or fantasy matchup weeks.
- **Coverage:** players with season games versus roster size. Missing histories
  display —; zero actual points remain a real zero.
- **Top 3 contribution:** share of positive player season FP totals supplied by
  the three largest contributors. Negative totals are shown, but excluded from
  the share denominator so percentages stay meaningful.
- **Box score:** summed points, rebounds, assists, steals, blocks, made threes,
  and turnovers. Shooting percentages divide total makes by total attempts,
  rather than averaging individual percentages. Missing inputs remain blank.
- **Weekly production:** FP per player appearance, grouped by Monday. Expand
  weekly details for dates, totals, averages, and appearance counts. Only weeks
  with observations are plotted; gaps do not imply zero production.

## Key players

| Card | Selection | Minimum sample |
| --- | --- | --- |
| Season anchor | Highest season FP total | 1 game |
| Per-game leader | Highest FP average | 1 game; fewer than 5 labeled early sample |
| Form leader | Largest last-five minus preceding-five FP average | 10 games |
| Biggest swings | Largest population standard deviation of game FP | 5 games |

The same player can lead several categories. A negative form-leader value means
even the strongest eligible change is a decline. These are descriptive summaries,
not forecasts, awards, or evidence of predictive accuracy. All roster members are
listed below in total-FP order; selecting a player opens the existing details.

## Data and boundaries

`season_review.py` receives the engine's cutoff-filtered observations and uses the
league season's October–September boundaries. Same-day live games must be confirmed
final by the existing engine. Duplicate player/game records keep the latest
correction. Full season history is aggregated before the public player-detail
history is capped at 25 games. Previous-season projection/lock bootstrap games
never enter these current-season totals.

The current scoring policy applies, including derived bonuses and approved
foul/rebound approximations. Unknown scoring rules or a statistics-provider error
produce an unavailable review instead of apparently complete partial totals.
Completed leagues read their saved season from the same SQLite database, without
new historical network requests. A season absent from the store stays empty.
Archived leagues remain excluded from the public report; local archive visibility
follows the existing team controls. This tab does not provide a cross-season
selector or historical roster ownership reconstruction.

The public JSON exports only allowlisted summary, box-score, weekly, and player
fields. The static site needs no database or additional scheduled job. It updates
with the existing daily publication and manual local refresh workflow. A retained
or expired report is historical information, dated by the report and review.

## Screenshots and checks

[Desktop review](screenshots/season-review-desktop.png) and
[phone review](screenshots/season-review-mobile.png) use generic team labels and
real stored October 20 observations. They intentionally show early-season coverage
and unavailable ten-game trends. No personal account details are included.

Tests cover full-season windows beyond 25 games, current/prior/future boundaries,
corrections, scoring bonuses, weighted shooting percentages, missing data,
negative totals, completed-season reads, export privacy, key-player sample gates,
and player-detail identity mapping. Responsive browser checks cover the team
cards, contributor details, weekly disclosure, and returning to the roster.
