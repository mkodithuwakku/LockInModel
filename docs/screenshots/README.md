# README screenshots

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
