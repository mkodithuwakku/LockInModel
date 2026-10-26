# Season review

Open **Season review** to see the selected team's season production; switch
teams with the usual team selector at the top. The default **My teams** view
still opens on the recommended roster sheet.

The tab holds three switchable views:

- **Season review** — the selected team's production under its own league
  formula, described below.
- **Compare teams** — every loaded team scored with the same default fantasy
  formula, so leagues with different custom rules compare fairly.
- **Shaqtin' a fool** — a hindsight audit of the most recent matchup week's
  recorded lock calls.

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

## The main season explorer

The main **Season review** has eight linked sections. Its shared scope controls
select the full season, last 7/30 calendar days, or an inclusive custom date
range; a player focus; home/away; and known NBA wins/losses. Presets end at the
report's observation cutoff, not the current browser clock. Unknown context is
included in the unfiltered view and excluded when a specific context is selected.
An invalid or empty date range shows an explicit empty state.

Filters are retained separately for each team during the browser session.
**Reset view** restores the full roster and season. A player's **Focus** button
recomputes the entire explorer for that player; clicking the portrait/name opens
the existing player profile. Local roster-table and archive filters only affect
their own tables, without changing the other sections.

### 1. Season pulse

Six metrics show total FP, FP per appearance, players with observations, 40+ FP
games and their hit rate, double/triple-doubles, and FP per observed game night.
Nightly totals depend on the schedule and roster size. Triple-doubles also count
as double-doubles.

Story cards identify the largest contributor, the strongest eligible last-five
versus previous-five change, and the mean deviation from prior-only benchmarks.
If even the strongest form change is negative, the card says so. The top-three
share and **effective contributors** describe concentration using positive player
FP totals: effective contributors = `1 / sum(share²)`, expressed as an equivalent
number of equally productive players. Nonpositive totals cannot create shares.

### 2. Scoring DNA

Signed bars show the FP contributed by each effective league scoring rule,
including deductions, double/triple-double and threshold bonuses. Values use the
same scoring engine as the report and reconcile with its game FP, subject to
display rounding. Approved rebound approximations and omitted foul penalties
are disclosed. Bonuses can stack; zero-weight rules are omitted.

The box-score fingerprint shows per-appearance production, totals, and input
coverage. Totals require that statistic in every selected game; missing or
imputed inputs stay blank. Shooting percentages pool makes/attempts rather than
averaging player percentages. eFG%, TS%, AST/TO and FP/min use the same rules as
comparison statistics below.

### 3. Trends and distribution

Switch between Monday-based weeks and calendar months, and between total FP and
FP per appearance. Expand period details for player counts, appearances,
production, changes from the preceding observed period, 40+ games and doubles.
Only observed periods are plotted; partial periods and gaps are not interpreted
as full weeks or zeroes.

A histogram places every appearance into exactly one fixed FP band (negative,
0–9.9, through 50–59.9, and 60+). Medians, quartiles, population standard
deviation and 60+ counts complement the mean. Quartiles and spread require five
observations. Current starter/bench/reserve groups describe current roster roles,
not historical lineup starts or lost bench points. The highest-total observed
night includes its date and appearance count.

### 4. Roster laboratory

Search names, filter positions and minimum appearances, and sort by volume,
per-game production, form, floor/ceiling, consistency, or efficiency. Four table
views show production, shooting/efficiency, reliability/form, or all statistics.
Missing-history players remain visible unless a sample filter excludes them.
Names open profiles; **Focus** updates all eight sections.

Metrics include per-game points/rebounds/assists/steals/blocks/threes/turnovers,
offensive/defensive rebounds, fouls, stocks (steals + blocks), shooting makes and
attempts, missed field goals/free throws, 3PA share, FTA/FGA, and FP/PTS/REB/AST
per 36 minutes. Per-36 statistics normalize observed playing time; they are not
playing-time forecasts. Positive denominators and complete inputs are required.
Reliability adds medians, quartiles, best/worst, 40+ hit rate, doubles, last played,
and the current run of above/below-baseline results. Sparklines show up to ten
selected games.

Last-five means use up to five selected observations. Form change needs ten
selected games. Floor/ceiling and population spread need five. Baseline streaks
stop at an unknown or equal-baseline result and use the selected chronological
sequence, so context filters can omit intervening games.

### 5. Weekly player map

Every cell is a player's mean FP for one observed week, with its game count.
Green/rose compare it with that player's mean in the selected window; neutral
means within ±10%, with a minimum 2 FP band. A dash means no observations.
This makes short samples and players who did not appear in a week visible.

### 6. Situational splits

Home/away, known NBA wins/losses, player-game spacing and opponent tables show
appearances, FP totals/averages, minutes, box production, TS% and FP/min.
Unknown metadata stays in labeled groups. NBA wins are not fantasy matchup wins.
Game spacing measures days since that player's prior observed season appearance,
not verified NBA team rest, injury status or missed scheduled games.

### 7. Record book

Portrait cards show highest and lowest observed game FP, plus the largest
positive and negative differences from a prior benchmark. Bench performances
can qualify here; they are performance records, not lock-decision judgments.
Six category cards identify total-production leaders in points, rebounds,
assists, steals, blocks and made threes, noting tied leaders and sample sizes.

Benchmarks use up to ten strictly earlier observed season games and need at
least three. The result being judged, other games on the same date, and later
games never enter its benchmark. Filtering the displayed window does not rebuild
these benchmarks. They are descriptive historical means, separate from archived
pregame forecasts and the recency-weighted model baseline.

### 8. Complete game archive

Every stored current-season appearance for the current roster is included,
independently of the 25-game player-profile limit. Search player/opponent/date,
filter 40+ games, below-baseline performances, doubles or triples, and sort by
date, FP, baseline lift or box stats. Forty rows display at a time with **Show
40 more**. CSV exports every matching row, including scoring components, not
just the visible page. String fields are quoted and spreadsheet-formula prefixes
are neutralized. Missing values export as empty cells.

Older saved reports without the complete tape show the previous summary layout
with a refresh notice. The explorer needs a new data report; changing assets
alone cannot reconstruct absent historical observations.

## Compare teams

**Compare teams** re-scores every loaded team's current roster under one default
fantasy formula (the configured `weights`, not each league's custom rules) and
ranks them by **roster average**: the mean of every covered player's individual
season FP average. Each player has equal weight, regardless of games played;
adding more players does not mechanically increase this average. It also shows
FP per appearance, appearance and coverage counts, and portrait cards for each
team's top three per-game scorers. The scope matches
the main review — observed season games for each team's current roster — so it
compares production, not Sleeper standings or locked scores.

Ranking choices separate several questions:

- **Roster average:** mean of covered players' individual season FP averages.
- **FP / appearance:** total FP divided by observed appearances, weighting busy
  players more heavily.
- **Top-five average:** mean FP/G for the five best observed per-game players;
  blank unless at least five players have observations.
- **Depth average:** mean FP/G for everyone after those five; blank if none.
- **Total FP:** accumulated volume, still affected by roster size and schedule.

Reserve players are included. Missing histories are excluded from averages,
while observed zero and negative results remain real values. Coverage and sample
sizes are visible; these rankings do not establish which roster will win.
The method disclosure includes each team's season and observation cutoff.

The team box-score table shows per-appearance counting stats and pooled,
attempt-weighted eFG%, TS%, AST/TO, and FP/min. The full player leaderboard
deduplicates shared NBA identities within each season, lists all owning fantasy
teams, and filters by team, position, name, and minimum games. Selecting a player
opens their existing league-specific details; leaderboard numbers retain default
scoring. Sort choices cover fantasy averages/totals, recent form, per-game box
stats, shooting, assist/turnover ratio, and FP/min. Ties share a rank; missing
values sort last.

Floor and ceiling are the 25th and 75th percentiles of observed game FP, and
consistency is population standard deviation, all requiring at least five games.
Form change requires ten games and compares the last five with the preceding
five. eFG% = `(FGM + 0.5 × FG3M) / FGA × 100`; TS% =
`PTS / (2 × (FGA + 0.44 × FTA)) × 100`. These are descriptive statistics,
not forecasts or possession-based ratings. Missing inputs and zero denominators
remain blank; imputed box stats do not enter these rates.

## Shaqtin' a fool

**Shaqtin' a fool** is a hindsight audit of the most recent matchup week with
recorded locks: the current week when locks exist, otherwise the newest archived
week. Expired matchup weeks are archived per league in `state/locks.json`
(bounded at 30 weeks), so completed weeks remain reviewable after rollover.

- **Retained FP:** every recorded locked score plus the best legal fill of the
  remaining lineup slots using each unlocked roster player's best game that week.
- **Perfect week:** the hindsight-optimal assignment of everyone's best game
  across every slot.
- **Left on table / efficiency:** the gap between the two, and retained as a
  share of perfect.

A lock is flagged only when unpinning it and re-filling its slot would have
scored more. If the same player refills the slot with a better later game it is
a *timing* mistake ("right player, wrong night"); if a teammate takes the slot it
is a *wrong-player* mistake. The audit uses each roster player's best observed
game of that week — a replay heuristic over completed games, not a judgment of
the information available when the locks were made. Weeks without recorded locks
or completed roster games do not invent mistakes. When games exist but no locks
are recorded, the retained and perfect totals use the same hindsight fill; the
UI explicitly says this is not a measured perfect decision record.

Mistake cards show both player portraits, locked-versus-better score bars, and
dates. Costs test one lock independently and may overlap; they must not be summed.
The seven-day timeline shows mean FP above/below each game's prior benchmark,
along with appearance and benchmark-coverage counts. The performance ledger
includes all observed current-roster games and can filter to below-baseline or
banked games. Missing or unplayed nights are not zero-point results.

Each benchmark is the arithmetic mean of up to ten strictly earlier stored
games under that league's scoring, with a minimum of three. Corrected game
records are deduplicated. The game being judged and later results never enter
its baseline. This descriptive benchmark is distinct from the recency-weighted
model forecast.

**Choke artist** selects the largest negative deviation among games whose date,
player, and observed score match a recorded lock. Bench performances cannot
create a banked-score shortfall. The optional **Final loss margin** input is
scoped to the team and review week for the current browser session. A hypothetical
return to baseline can flip that entered margin only if its gain strictly exceeds
the margin (equality merely ties). Every other locked score stays fixed.
Opponent totals, final matchup status, and a real counterfactual win are not
verified. Missing prior samples or recorded locks produce an explicit empty state.

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

The public JSON exports allowlisted summary, box-score, weekly, player,
full season game tape and effective scoring-rule fields, cross-team comparison,
and lock-audit fields. Full tape is generated before player-detail history is
truncated and omitted from the duplicate cross-team comparison calculation.
Client-side aggregation supports filters without a new database, dependency,
endpoint, or scheduled job. It updates
with the existing daily publication and manual local refresh workflow. A retained
or expired report is historical information, dated by the report and review.
Saved reports generated before these fields were added need a data refresh to
populate the complete player comparison and performance tape.

## Screenshots and checks

[Desktop overview](screenshots/season-review-desktop.png),
[phone overview](screenshots/season-review-mobile.png),
[scoring DNA](screenshots/season-scoring-desktop.png)
([phone](screenshots/season-scoring-mobile.png)),
[roster lab](screenshots/season-roster-lab-desktop.png), and
[records](screenshots/season-records-desktop.png) use generic teams and explicitly
illustrative statistics. They demonstrate populated analysis states, not
observed NBA results, actual ownership, or live advice.

The expanded [team comparison](screenshots/team-comparison-desktop.png),
[weekly film](screenshots/weekly-film-desktop.png), and
[compact waivers](screenshots/compact-waivers-desktop.png) use generic teams and
explicitly illustrative statistics to exercise populated states.
[Phone comparison](screenshots/team-comparison-mobile.png),
[phone film](screenshots/weekly-film-mobile.png), and
[phone waivers](screenshots/compact-waivers-mobile.png) show the same fixture.
These examples do not represent observed NBA results or current recommendations.

Tests cover full-season windows beyond 25 games, current/prior/future boundaries,
corrections, scoring bonuses, weighted shooting percentages, missing data,
negative totals, completed-season reads, export privacy, key-player sample gates,
weekly lock-audit timing/player mistakes and empty states, lock-week archival on
rollover, and player-detail identity mapping. Responsive browser checks cover the team
cards, contributor details, weekly disclosure, and returning to the roster.

## Season Badge race

**Badge race** lives in its own tab and counts awards across the selected
league's season through the previous night. It opens on the **NBA-wide** pool,
with a **My roster** toggle (current players, including awards before joining).
Four compact cards show total
badges, negative badges (Chaos leader), milestones, and distinct badge types.
The leaderboard selector also includes every individual badge. Competition ranks
preserve ties; the first ten places are shown, including ties at tenth. Expand
**Leaders for all 44 badges** for a category-by-category view.

Every player name in the race opens a player card, including players on other
fantasy rosters. Leaderboard rows and highlight cards include NBA portraits with
an initials fallback if the image cannot load. The category disclosure keeps
clickable names without repeating portraits. Cards use details from the selected
league where available; players with only badge history show their identity and
season awards, with an explicit note that game-by-game performance is not included.
They are not labeled as pickup recommendations.

All player cards include a compact **Season badges** section: total awards,
chaos (negative indicators), milestones, and variety (distinct types, shown as
earned out of the effective cap of 43, or 42 for ages 24–31, accounting for
mutually exclusive age awards). Expand
**Earned badges** for each earned type and its repeat count. Counts use the same
league/season ledger as the race and include games before joining the roster.
Unavailable history displays an unavailable message rather than zero; a covered
player with no awards displays zero. Saved totals retain their date and label.
Click or tap outside the card to close it at any scroll position; Escape and the
close button also work. Clicking inside or dragging from inside to outside keeps
the card open.

Each badge counts once per player per night, regardless of its daily rank.
A player can earn several different badges on the same night. Milestones include
double-/triple-doubles and the highest qualifying tier for each stat; repeat
qualifying streak nights earn repeat awards. Negative categories are Bricklayer,
Meatball sub, Oh my goodness Valentine, Butterfingers, Below expectations,
Slow night, Cold spell, and Along for the ride. A high FP score in a loss does
not count as negative. The coverage disclosure lists these categories and the
available game dates and forecast coverage.

`badge_store.py` persists the ledger in the existing local database and reuses
the daily award rules. Historical observations can backfill earned badges;
projection-surprise awards require genuine saved pregame forecasts. Repeated
refreshes do not add duplicates. Corrected nights replace their old awards and
earlier stat corrections invalidate later streak calculations. Formula changes
use separate tallies. Missing data stays missing, and completed leagues read
saved awards without historical network requests. Test Week does not fabricate
a season ledger. The static website receives only aggregate public counts.

[Desktop Badge race](screenshots/season-badge-race-desktop.png) and
[phone Badge race](screenshots/season-badge-race-mobile.png) show generic team
labels with the stored opening-night results. Ledger tests cover idempotency,
corrections, streak invalidation, date/formula isolation, forecasts, and export
privacy; frontend tests cover roster scope, metrics, and tied ranks.


[Desktop player badges](screenshots/player-season-badges-desktop.png) and
[phone player badges](screenshots/player-season-badges-mobile.png) show an
NBA-wide player outside the sample roster with the earned-badge list expanded.
Browser checks cover roster/highlight/category links, keyboard activation and
focus return, backdrop dismissal after scrolling, and no horizontal overflow at
320px, 390px, and 1280px. Node tests cover identity resolution, league isolation,
repeat counts, and zero versus unavailable histories.
