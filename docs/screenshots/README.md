# README screenshots

## Expanded team comparison, weekly film, and compact waivers

- `team-comparison-desktop.png` / `team-comparison-mobile.png`: roster-size-aware
  rankings, quality/depth/volume summaries, portrait leaders, pooled box-score
  rates, and the full filterable player leaderboard.
- `weekly-film-desktop.png` / `weekly-film-mobile.png`: a banked-game shortfall,
  an entered 8.5 FP loss-margin what-if, visual lock regret, daily deviation bars,
  and the player performance ledger.
- `compact-waivers-desktop.png` / `compact-waivers-mobile.png`: compact add
  candidates with roster-player portraits, positive/negative fit values,
  add/drop symbols, and expandable sample/scoring notes.

These six captures use **illustrative statistics and generic teams**, explicitly
labeled in the UI. Names/headshots identify real NBA players, but fixture
performances, roster membership, and lock decisions are invented for layout and
interaction checks. They are not observed NBA results, actual matchup losses,
or live waiver advice. Phone captures use 390px; layout checks additionally cover
320px, 1024px, and 1440px. Missing headshots use initials.

## Current restrained plum accents and weekly projections

- `roster-first-desktop.png`: illustrative five-player league with three active
  slots, using stored forecasts and the optimizer’s assignment for October 21.
  Charcoal surfaces carry a subtle plum undertone, with muted purple accents and
  small soft-gold details. Upcoming game tiles show projected
  FP beside the matchup.
  Recommended starters occupy the sheet; the bench follows. The compact header
  keeps players first, with summary counters and insights below the full roster. The preview is not
  a live league or a freshly fetched report.
- `roster-first-mobile.png`: the same compact roster and lineup summary at 390px.
- `season-blend-mobile.png`: player details showing a 9-FP completed game, an 11.9-FP projection, and one current-season plus nine prior-season games for both the projection and lock baseline. The configured window is 10 games. This documents provenance, not measured prediction accuracy.

Earlier screenshots below predate the restrained plum palette and weekly tile forecasts,
and most also predate the integrated lineup. Their separate lineup
cards and synced-starter ordering are historical feature examples.

All roster captures predate the recolored position slots (PG/SG/G/SF/PF/F/C/UTIL
now use distinct hues), the off-day placeholder rows, and the add/drop waiver
card that can appear between the recommended lineup and the bench. A refreshed
roster capture showing the new slot palette and the swap card is outstanding.

## Earlier visual identity

- `identity-desktop.png`: generic sample roster, with the interlocking LI logo,
  charcoal/plum surfaces, copper/gold accents and full-roster forecasts.
- `identity-mobile.png`: the same generic sample at 390px. Its team has no external
  photo, demonstrating the initials fallback. Real imported league photos are
  verified separately and excluded from committed screenshots.

## Expanded daily badge captures

- `expanded-badges-mobile.png`: generic team labels with real October 20 observations, including the new free-throw and/or missed-three categories. The tiny roster strip still caps at three icons; player details show the full breakdown. Projection-comparison badges need a previously saved pregame benchmark and are not fabricated for this capture.

## Daily badge captures

- `daily-badges-desktop.png`: generic Night Shift practice roster, showing small
  previous-night icons and the overflow count beside player names.
- `daily-badges-mobile.png`: phone player details with every earned badge's
  category, observed value, rank and date.

These use real December 25, 2025 observations and the December 26 practice clock,
not current live recommendations. They use the current warm palette. The existing
identity captures predate badges.

The older feature captures below use the earlier navy/teal palette. They remain feature
walkthroughs, not examples of the current branding.


These captures show generic sample teams and historical performances through
December 25, 2025. They do not show current recommendations or personal account
settings. The desktop Test Week uses an isolated practice-state file.

- `team-insights-desktop.png`: 1440px desktop with Recent form beside the roster,
  five-game averages, changes versus the previous five games, and sparklines.
- `team-insights-mobile.png`: 390px phone with the compact form panel above the
  roster. Both new captures use generic teams in an isolated Test Week.
- `test-week-night.png` (older layout; decorative court now removed): desktop Test Week scrolled to the practice clock,
  banked total, summary, and compact roster with weekly game tiles.
- `player-detail.png`: desktop player sheet with latest score, baseline,
  remaining opportunities, weekly opponents, explanation, and production chart.
- `mobile-roster.png`: 390px phone roster with position slots, team labels,
  grouped starters/bench, decision badges, and observed points in game tiles.
- `mobile-player-detail.png`: the phone bottom sheet with the same player context.

The compact layout was checked at 320px and 390px phone widths and 1024px desktop,
including overflow, search, bench filters, player details, pickup browsing, and
Test Week score banking. A 390px roster viewport fits about seven complete rows
after scrolling past the header. These are browser checks, not physical-device
certification or an automated browser test suite.

The sample position assignments are explicit practice inputs. Current injury
labels are omitted from historical replay; historical team labels come from the
observed game data. Future replay scores remain hidden until revealed.

When these screens change, replace affected captures and keep captions accurate.
Keep personal account names, email addresses, and connection settings out of the
images. Wait for loading and transient toasts to finish before capture.

The older roster/player images document the previous roster and practice layout.
They predate the local SQLite/daily publisher changes and do not demonstrate the current live
scoring-policy notes, 26-hour expiry, or wake catch-up. A generic live Data alerts
capture with omitted fouls and rebound approximation is the remaining screenshot
to capture; do not interpret the historical images as verification of that state.

Recent form was checked at 1440px desktop, 1024px tablet, and 390px/320px phone
widths, including full-team expansion and correct player-detail links. The chart
uses observed historical scores; these captures do not verify live provider uptime.

## Daily lineup captures

- `daily-lineup-desktop.png`: generic Test Week roster at 1280px, showing the exact daily assignment and total alongside Recent form.
- `daily-lineup-mobile.png`: 390px view of the same five-slot sample configuration above Recent form.

The isolated sample run uses PG, SG, F, C, and UTIL slots and historical December 25, 2025 schedules. Its pregame projections use only earlier games, while night replay displays the day's observed roster scores separately. This is a demonstration, not a claim of historical injury/lineup eligibility or prediction accuracy. The older team-insights images predate the daily lineup card.

Verified browser interactions include lineup-to-player detail links, excluded-player expansion, switching to a team with a different configuration, and no horizontal overflow at 320px, 390px, 1024px, and 1280px. These are manual browser checks, not device certification.

## Full-roster projection captures

- `roster-projections-desktop.png`: generic five-player sample roster at 1280px, with current-season Sleeper / RotoWire forecasts rescored using the checked-in sample weights. Every player is deliberately on the bench to demonstrate independent forecast coverage.
- `player-projections-mobile.png`: 390px player details showing a rookie's full projected box score and source date. No NBA game history is invented.

These use an isolated in-memory configuration, not personal team names or account settings. The earlier daily-lineup and team-insights screenshots predate per-row projected stat lines; retain them only as demonstrations of their specific features. Current-season projections are estimates, not observed scores or verified prediction accuracy.

- `available-players-desktop.png` and `available-players-mobile.png`: current charcoal/plum theme, generic team labels, history-independent unrostered-player directory with compact, uncropped 40px portraits, observed averages where available and empty trend placeholders. Public NBA identities only; no personal team photos or account details.


## Season review captures

- `season-review-desktop.png`: 1440px season explorer with shared filters,
  section navigation, six production metrics and evidence-based story cards.
- `season-review-mobile.png`: 390px production metrics and player stories.
- `season-scoring-desktop.png` / `season-scoring-mobile.png`: signed league
  scoring contributions, per-appearance box production and efficiency.
- `season-roster-lab-desktop.png`: roster statistics, portrait rows with recent
  sparklines, focus controls and the player-by-week map.
- `season-records-desktop.png`: record performances and category leaders.

These replace the earlier summary-only captures. They use generic teams and
**illustrative statistics**, with real NBA identities/headshots. Performances,
ownership and league settings are fixture inputs, not actual NBA results or live
advice. No personal account details are included. Totals describe current-roster
production, not Sleeper locked points.
The roster remains the first/default view; Season review is a separate tab.
Browser checks cover all eight sections at 320px, 390px, 1024px and 1440px,
including shared filters, invalid/empty ranges, table views, single-player focus,
archive search/sorting/pagination/CSV, player dialogs and switching teams.


## Season badge cards

- `season-badge-race-desktop.png` and `season-badge-race-mobile.png`: NBA-wide
  Chaos leaderboard with player portraits and clickable highlight/leader names.
- `player-season-badges-desktop.png` and `player-season-badges-mobile.png`: OG
  Anunoby's card outside the illustrative roster, with four compact season counts
  and the earned-badge list expanded. The disclosure is collapsed when first opened.

These use generic sample team labels and stored October 20, 2026 awards. They
show the selected league's saved totals, not a new provider refresh. NBA portraits
load from the NBA CDN with initials if unavailable. For these captures, the
headless browser’s CDN transport was bridged through the HTTP request client
using real image responses; separate checks verified the fallback state. Older player-card screenshots
predate the Season badges section; use these captures for its current layout.
