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

The default CLI and dashboard use local replay. Changing dates does not fetch NBA data. Player portraits are served from the local image cache, with a neutral placeholder for missing portraits. Font files currently load from Google Fonts; system fallbacks work offline. Numerical replay and player images do not require external connections.

## Sleeper

Open **Sleeper connection**, enter a username and season start year, and sync. The app imports all of the user's NBA teams for that year. No Sleeper credentials are requested. Offseason/completed leagues can be imported; no leagues for a year leaves existing teams intact.

Imports use cached, paced reads. A failed request preserves the previous full configuration. Scoring gaps are displayed per league. The application never submits locks or roster transactions to Sleeper.

## Live reports and email

```bash
python main.py --live
python main.py --live --send --daily
```

The first command explicitly retrieves current inputs but does not send email. The second is intended for the noon automated run. It refreshes Sleeper rosters, skips completed leagues in the offseason, and reports failures instead of inventing recommendations. NBA observations through the previous day are used for noon analysis.

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
