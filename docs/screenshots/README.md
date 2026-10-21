# README screenshots

These captures show generic sample teams and historical performances through
December 25, 2025. They do not show current recommendations or personal account
settings. The desktop Test Week uses an isolated practice-state file.

- `test-week-night.png`: desktop Test Week scrolled to the practice clock,
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

The existing images document the roster and practice layout. They predate the
local SQLite/daily publisher changes and do not demonstrate the current live
scoring-policy notes, 26-hour expiry, or wake catch-up. A generic live Data alerts
capture with omitted fouls and rebound approximation is the remaining screenshot
to capture; do not interpret the historical images as verification of that state.
