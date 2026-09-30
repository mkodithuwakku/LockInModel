# README screenshots

These images were captured from the redesigned application in a local browser
using the sample configuration and an isolated practice-state file. They show
historical data through December 25, 2025, not current recommendations. Personal
configuration and the user's saved practice run were not changed.

- `test-week-night.png`: full desktop Test Week after revealing Thursday's games;
  shows the practice clock, scoreboard, roster decisions, court diagram, and a
  score banked earlier in the week. Nightly box scores are collapsed by default.
- `player-detail.png`: a player with usable historical data; show the latest score,
  baseline, opportunities, explanation, and recent performance chart.
- `mobile-roster.png`: the 390-pixel-wide roster view, scrolled to the scoreboard
  and player rows.

Verification covered 320, 390, 768, 1024, and 1440-pixel viewport widths without
horizontal page overflow; search, filters, team switching, pickup and alert views,
connection and roster dialogs, practice advance/bank/persistence, roster toggling,
and keyboard opening/closing of player details. Browser errors were empty. These
are manual browser checks, not a new automated CI browser suite.

The captures were refreshed after correcting transparent headshots: initials are
visible while loading or after an image error, and hidden behind a successfully
loaded portrait. The follow-up browser check covered Giannis's cached headshot,
the loading state, and a deliberately failed image request.

When these screens change, replace the relevant capture using sample/practice data
and keep the same filename where practical. Wait for loading and transient toasts
to finish. Keep personal account names, email addresses, and connection settings
out of screenshots. Verify README captions still describe the visible state.
