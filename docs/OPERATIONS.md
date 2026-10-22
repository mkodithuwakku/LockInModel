# Setup and operations

## Installation

Use the repository directory containing `app.py` and `requirements.txt`:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python capture.py
python app.py
```

Open [localhost:8765](http://127.0.0.1:8765). `gui_select.py` is a compatibility launcher that starts the same app and opens a browser. No frontend build is required. To install runtime dependencies only, use `requirements.txt`.

The inspected local interpreter is Python 3.9.6. Top-level dependencies are pinned, and CI is configured for Python 3.11/3.12. The urllib3 1.26.20 pin supports the existing LibreSSL-based local interpreter; a modern Python/OpenSSL environment and refreshed dependency matrix remain a follow-up. Do not copy the old virtual environment to another computer.

## Capture and replay

```bash
python capture.py
python main.py --date 2025-12-25
```

Capture retrieves four archived tables from a GitHub revision selected and pinned locally on its first run, reuses existing downloads, validates their schemas and identifiers, and generates a checksum manifest. A fresh checkout resolves the archive's current revision rather than using the committed manifest's revision. It does not call NBA Stats. See [Historical replay](HISTORICAL_REPLAY.md) for scope and caveats.

The dashboard opens the saved live workspace; **Test Week** runs offline practice. The CLI defaults to end-of-day replay. Advancing the practice clock does not fetch NBA data. Fantasy team photos refresh with Sleeper sync and load from Sleeper’s CDN, with initials on failure. Player portraits are served from the local image cache, with a neutral placeholder for missing portraits. Font files currently load from Google Fonts; system fallbacks work offline. Numerical replay and player images do not require external connections.

## Sleeper

Open **Sleeper connection**, enter a username and season start year, and sync. The app imports all of the user's NBA teams for that year. No Sleeper credentials are requested. Offseason/completed leagues can be imported; no leagues for a year leaves existing teams intact.

Imports use cached, paced reads. A failed request preserves the previous full configuration. Scoring gaps are displayed per league. The application never submits locks or roster transactions to Sleeper.

## Live reports and email

```bash
python main.py --live
python main.py --live --send --daily
```

The first command explicitly retrieves current inputs but does not send email. The second is intended for the noon automated run. It refreshes Sleeper rosters, skips completed, pre-draft, and drafting leagues, and reports failures instead of inventing recommendations. Live analysis includes completed observations through the refresh day; same-day games require a confirmed final schedule status.

Delivery requires local EMAIL_USER and EMAIL_APP_PASSWORD and an intended recipient in `config.local.yaml`. A report is saved before attempting delivery. The application records an attempt before SMTP to avoid duplicate automatic sends after an ambiguous failure. If delivery is uncertain, investigate before manually changing the ledger; automatically retrying may send duplicates.

Pickup alerts are limited to candidates with complete scoring coverage, known league ownership, and positive estimated roster fit. Repeated alerts have a 72-hour cooldown unless the signal score improves by at least 10 or projected FP by at least 3. Alert state advances only after successful delivery.

The configured app password was found in public Git history. A local hash guard prevents sending with that password. Revoke it in Google, create a replacement, and update `.env` locally. Do not paste the password into a task or commit it.

## Noon email automation

The requested schedule is noon in America/Edmonton. The Codex automation runs the daily CLI command locally; the computer and local execution environment must be available. It should remain quiet when all leagues are completed or the day was already processed, and surface actionable failures without repeated unchanged notifications. It must not bypass the exposed-credential guard or launch historical capture.

Website publication is separate: a native macOS LaunchAgent targets 7:00 AM America/Edmonton, checks every 15 minutes, and catches up after wake/login. It requires neither Codex nor Flask to remain open. Both paths reuse the same successful daily SQLite refresh. The publisher sends no email; its retry/completion ledger is separate from email delivery suppression.

## Troubleshooting

| Symptom | Meaning / action |
| --- | --- |
| SCHEDULE UNAVAILABLE | Upcoming data failed or was empty; no decision was issued |
| SCORING GAP | An unknown nonzero league rule or another required stat remains unsupported; displayed FP is partial |
| Foul/rebound information note | The documented approximation is active; this alone does not block recommendations |
| DATA ISSUE | A required field is missing/invalid or the provider failed |
| STALE DATA | Report is older than 26 hours, belongs to a previous fantasy week, or has an invalid/future timestamp |
| SEASON FINISHED | Imported league is completed; no active analysis is needed |
| Player has no game/history | No eligible observation exists by the selected date |
| Refresh reports cooldown | Wait for the persistent host cooldown; repeated refreshes will not bypass it |
| Imported roster cannot be edited | Make changes in Sleeper, then sync; local teams remain editable |
| Replay checksum error | A required fixture file changed or is missing; inspect before recapturing |
| Email blocked | Replace the publicly exposed app password or complete local settings |
| Email already attempted | Daily duplicate suppression; inspect `state/email-delivery.json` |
| Missing picture | A local portrait was not captured; a neutral placeholder is used |
| Website unchanged after source push | `main` runs tests only; publish locally with `publication.py run --force` or wait for the next daily slot |
| Publication pending or retrying | Inspect `publication.py status` and publication logs; a push is not complete until the live report ID is confirmed |

## Verification

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m black --check *.py tests
# Node 20+ is needed only for these frontend policy tests.
node --test tests/*.test.cjs
```

Tests prohibit sockets and cover normalization, generic bonus thresholds, foul/rebound fallbacks, sparse histories, future-data exclusion, failure cooldowns, import atomicity, roster editing, pickup signals, and email guards. Store tests cover correction upserts, failed-refresh retention, forecast snapshots, and season badge award ledgers. Publisher tests cover daily slots, retries, pending deployment confirmation, and exported files pushed to a temporary local Git remote. Node checks cover hosted report policies, recent form deltas, performance colour baselines, and Season Review aggregates. Real-fixture tests skip on a clean checkout until capture has run. Manual browser checks are separate; CI does not include an automated browser suite or a physical sleep/wake test.

The Flask app binds only to loopback and is intended for one local user. The separately hosted [GitHub Pages dashboard](HOSTING.md) serves static reports without exposing Flask or allowing edits.

## Email activation on this computer

The native Codex automation **LockIn noon report** is configured for noon, America/Edmonton. It runs `.venv/bin/python main.py --live --send --daily` in this repository. It is a local automation, so keep the computer awake, connected, and Codex available. The Flask dashboard does not need to be open. A hosted scheduler would be needed for reliable delivery while this computer is off.

Before delivery, revoke the previously exposed Google app password and generate a new one using [Google's app-password instructions](https://support.google.com/accounts/answer/185833?hl=en). Google requires 2-Step Verification for app passwords; managed account policy can restrict availability. Update `EMAIL_APP_PASSWORD` in ignored `.env` locally, and verify `EMAIL_USER` and the recipient in `config.local.yaml`. Do not paste the password into chat or commit it. The delivery guard automatically accepts a different password; do not remove the guard file to reuse the exposed password.

The daily command launches a fresh process and rereads `.env`. No new automation is needed after replacement. No email is sent while every league is completed or awaiting its season. When active, the report sends recommendations or explicit data-error/scoring-gap notices; unknown scoring rules still prevent actionable lock calls; unavailable fouls and missing rebound splits use the approved approximation policy. No actual SMTP delivery has been verified yet. Once the credential is replaced, a separately requested one-off test email can verify delivery without fetching NBA data.

## New leagues and archives

Both **Refresh live data** and the noon command check the current Sleeper season, then refresh the last saved year when the new year has no leagues. The connection dialog also allows explicit season selection; 2026 means 2026–27. Drafted players appear after a successful sync (cached Sleeper responses can be up to 15 minutes old). This is polling, not an instant draft feed.

Teams are keyed by league ID, so re-sync updates an existing team and distinct leagues may legitimately share a name. Importing a newer season archives earlier seasons for the same account. A league absent from a successful, nonempty same-season league list is archived. Archives are hidden by default and excluded from reports; **Show archived leagues** reveals saved rosters. An empty or failed import preserves existing teams as a conservative safeguard. A stale unused league still returned as active by Sleeper cannot be identified automatically as unwanted.

## Hosted daily report

The Mac publishes the public dashboard with `publication.py`; GitHub serves only exported files from `gh-pages`. The former cloud data-fetching workflow has been removed. The existing local noon email automation remains separate and retains its credential guard.

```bash
.venv/bin/python publication.py run --force --setup-pages
.venv/bin/python publication.py install
.venv/bin/python publication.py status
```

Initial setup publishes the branch, configures Pages to serve it, and requests the first Pages build. Installation creates `~/Library/LaunchAgents/com.lockin.publish.plist`; Codex and Flask do not need to remain open. Keep the Mac logged in and connected for updates. The agent runs after missed sleep intervals/login and retries transient failures. Inspect `logs/publication.log`, `logs/publication-error.log`, and `state/publication.json`. A manual `publication.py run --force` bypasses the daily publication guard, and fetches game updates again, even on the same day; it still respects provider cooldowns. Source changes made on another computer must be pulled into this checkout before publication. See [Hosting](HOSTING.md) for verification and recovery.

## Database maintenance

`data/lockin.sqlite3` is created automatically for live game history. No database service or manual schema setup is needed. The first season refresh reads the full season, later daily refreshes overlap seven days, and weekly full reconciliation catches older corrections. Failed downloads preserve prior observations and do not mark a refresh successful. Retained data does not authorize recommendations when current inputs failed.

Back up the database while no refresh is running, along with private configuration and state. Do not delete it as a routine cache reset: that discards the accumulated history and requires a new full-season fetch. HTTP caches and immutable replay fixtures have separate roles. All of these local runtime files remain ignored by Git; the hosted site receives only the allowlisted display snapshot.
