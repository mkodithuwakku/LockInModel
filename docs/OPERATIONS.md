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

Capture retrieves four archived tables from a fixed GitHub revision, reuses existing downloads, validates their schemas and identifiers, and generates a checksum manifest. It does not call NBA Stats. See [Historical replay](HISTORICAL_REPLAY.md) for scope and caveats.

The dashboard opens the saved live workspace; **Test Week** runs offline practice. The CLI defaults to end-of-day replay. Advancing the practice clock does not fetch NBA data. Player portraits are served from the local image cache, with a neutral placeholder for missing portraits. Font files currently load from Google Fonts; system fallbacks work offline. Numerical replay and player images do not require external connections.

## Sleeper

Open **Sleeper connection**, enter a username and season start year, and sync. The app imports all of the user's NBA teams for that year. No Sleeper credentials are requested. Offseason/completed leagues can be imported; no leagues for a year leaves existing teams intact.

Imports use cached, paced reads. A failed request preserves the previous full configuration. Scoring gaps are displayed per league. The application never submits locks or roster transactions to Sleeper.

## Live reports and email

```bash
python main.py --live
python main.py --live --send --daily
```

The first command explicitly retrieves current inputs but does not send email. The second is intended for the noon automated run. It refreshes Sleeper rosters, skips completed, pre-draft, and drafting leagues, and reports failures instead of inventing recommendations. NBA observations through the previous day are used for noon analysis.

Delivery requires local EMAIL_USER and EMAIL_APP_PASSWORD and an intended recipient in `config.local.yaml`. A report is saved before attempting delivery. The application records an attempt before SMTP to avoid duplicate automatic sends after an ambiguous failure. If delivery is uncertain, investigate before manually changing the ledger; automatically retrying may send duplicates.

Pickup alerts are limited to candidates with complete scoring coverage, known league ownership, and positive estimated roster fit. Repeated alerts have a 72-hour cooldown unless the signal score improves by at least 10 or projected FP by at least 3. Alert state advances only after successful delivery.

The configured app password was found in public Git history. A local hash guard prevents sending with that password. Revoke it in Google, create a replacement, and update `.env` locally. Do not paste the password into a task or commit it.

## Noon automation

The requested schedule is noon in America/Edmonton. The Codex automation runs the daily CLI command locally; the computer and local execution environment must be available. It should remain quiet when all leagues are completed or the day was already processed, and surface actionable failures without repeated unchanged notifications. It must not bypass the exposed-credential guard or launch historical capture.

## Troubleshooting

| Symptom | Meaning / action |
| --- | --- |
| SCHEDULE UNAVAILABLE | Upcoming data failed or was empty; no decision was issued |
| SCORING GAP | Nonzero league rules require unavailable stats; displayed FP is partial |
| DATA ISSUE | A required field is missing/invalid or the provider failed |
| STALE DATA | Saved live report is older than six hours or from another day |
| SEASON FINISHED | Imported league is completed; no active analysis is needed |
| Player has no game/history | No eligible observation exists by the selected date |
| Refresh reports cooldown | Wait for the persistent host cooldown; repeated refreshes will not bypass it |
| Imported roster cannot be edited | Make changes in Sleeper, then sync; local teams remain editable |
| Replay checksum error | A required fixture file changed or is missing; inspect before recapturing |
| Email blocked | Replace the publicly exposed app password or complete local settings |
| Email already attempted | Daily duplicate suppression; inspect `state/email-delivery.json` |
| Missing picture | A local portrait was not captured; a neutral placeholder is used |

## Verification

```bash
python -m pytest -q
python -m black --check *.py tests
```

Tests prohibit sockets and cover normalization, bonus thresholds, sparse histories, future-data exclusion, failure cooldowns, import atomicity, roster editing, pickup signals, and email guards. Real-fixture tests skip on a clean checkout until capture has run. Browser checks exercise the actual local interface separately.

The app binds only to loopback and is intended for one local user. It is not configured for internet hosting or multiple simultaneous editors.

## Email activation on this computer

The native Codex automation **LockIn noon report** is configured for noon, America/Edmonton. It runs `.venv/bin/python main.py --live --send --daily` in this repository. It is a local automation, so keep the computer awake, connected, and Codex available. The Flask dashboard does not need to be open. A hosted scheduler would be needed for reliable delivery while this computer is off.

Before delivery, revoke the previously exposed Google app password and generate a new one using [Google's app-password instructions](https://support.google.com/accounts/answer/185833?hl=en). Google requires 2-Step Verification for app passwords; managed account policy can restrict availability. Update `EMAIL_APP_PASSWORD` in ignored `.env` locally, and verify `EMAIL_USER` and the recipient in `config.local.yaml`. Do not paste the password into chat or commit it. The delivery guard automatically accepts a different password; do not remove the guard file to reuse the exposed password.

The daily command launches a fresh process and rereads `.env`. No new automation is needed after replacement. No email is sent while every league is completed or awaiting its season. When active, the report sends recommendations or explicit data-error/scoring-gap notices; missing foul penalties still prevent actionable lock calls. No actual SMTP delivery has been verified yet. Once the credential is replaced, a separately requested one-off test email can verify delivery without fetching NBA data.

## New leagues and archives

Both **Refresh live data** and the noon command check the current Sleeper season, then refresh the last saved year when the new year has no leagues. The connection dialog also allows explicit season selection; 2026 means 2026–27. Drafted players appear after a successful sync (cached Sleeper responses can be up to 15 minutes old). This is polling, not an instant draft feed.

Teams are keyed by league ID, so re-sync updates an existing team and distinct leagues may legitimately share a name. Importing a newer season archives earlier seasons for the same account. A league absent from a successful, nonempty same-season league list is archived. Archives are hidden by default and excluded from reports; **Show archived leagues** reveals saved rosters. An empty or failed import preserves existing teams as a conservative safeguard. A stale unused league still returned as active by Sleeper cannot be identified automatically as unwanted.
