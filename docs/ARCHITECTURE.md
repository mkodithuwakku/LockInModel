# Architecture and data contracts

## Modules

| Module | Responsibility |
| --- | --- |
| `app.py` | Flask routes, same-origin protection, background refresh jobs, dashboard cache |
| `web/` | Responsive interface, team navigation, player details, roster editing, import UI |
| `storage.py` | Canonical YAML loading/validation; atomic JSON/YAML writes |
| `simulation.py` | Persistent morning/night replay, isolated practice roster snapshot, revision checks, banked scores |
| `engine.py` | Shared dashboard/report orchestration and per-input decision reuse |
| `providers.py` | Explicit fixture/live input policies |
| `fetch_data.py` | NBA adapters, name matching, strict normalization, dates, bonuses |
| `game_store.py` | SQLite player-game history, daily overlap upserts, weekly full reconciliation |
| `publication.py` | Local static publication, deployment verification, retry ledger, macOS wake catch-up |
| `transport.py` | Persistent response cache, request serialization/pacing, cooldown circuit |
| `scoring.py` | Configured weighted FP calculation |
| `decide.py` | One player's weekly result and failure states |
| `model.py` | Weighted baseline, variance guards, rarity, future-score probability |
| `pickups.py` | Separate-window improvement screening and roster fit |
| `sleeper.py` | Read-only roster/scoring import, ordered lineup slots, NBA team/injury metadata, complete ownership snapshot |
| `schedule.py` | Validated, cached full-season schedule; weekly opponents and remaining-game counts |
| `capture.py` | Resumable immutable archive capture and fixture manifest |
| `main.py` | CLI reports, daily delivery guard, pickup alert cooldown |
| `notify.py` | SMTP transport with an explicit timeout |
| `gui_select.py` | Compatibility launcher for the web dashboard |
| `logger.py` | Console and optional file logging |

## Request flow

The browser loads `/api/bootstrap` for the CSRF token, local player directory, fixture dates, and saved Sleeper connection settings. `/api/dashboard` reads replay inputs or a saved live report. It does not silently refresh NBA data.

GET/POST `/api/test-week` reads or advances the offline practice run, banks scores, and edits practice starters/rosters. Every POST requires CSRF and the current run revision.

POST `/api/roster` edits local roster membership or starter selection and atomically saves YAML. POST `/api/sync` starts a Sleeper import. POST `/api/refresh` explicitly starts live analysis. Long operations use one background worker and expose `/api/jobs/<id>`; another refresh is rejected while one is running.

The server binds to `127.0.0.1:8765`. Trusted hosts are localhost and loopback. Cross-site requests are rejected, and mutations require JSON plus the session's CSRF token. There is no public authentication layer: do not expose this development server to a network.

## Canonical configuration

`config.local.yaml` is authoritative when present; otherwise `config.yaml` supplies defaults. Paths resolve relative to the repository module directory, independently of the shell's current directory. Roster writes use a reentrant in-process lock, temporary files, fsync, and atomic replacement.

The application no longer reads `state/starters.json`. Existing multi-team rosters were migrated into the local YAML. Imported teams use stable `sleeper-<league_id>` IDs and retain the source season, scoring settings, roster ownership, and synchronization time.

## NBA request behavior

Requests pass through `CachedHTTP`. Cache keys include URL and query parameters. Cached responses have explicit freshness lifetimes; stale responses do not masquerade as fresh data. Offline cache reads fail instead of opening a connection.

A filesystem lock serializes requests across processes. Requests are paced per host, with a three-second interval for NBA Stats and a one-second interval for Sleeper. The client uses connect/read timeouts. HTTP 429 honors Retry-After, with a conservative fallback; transport or JSON failures open a five-minute host cooldown. It makes one attempt and requires a later explicit retry, avoiding retry storms.

The live provider first loads one Sleeper regular-season schedule (six-hour cache, three-second pacing). It validates records and season dates, shares that calendar across all players, and uses the current Sleeper NBA team assignment for live scheduling. Before the first game can enter the observation cutoff, it skips NBA Stats entirely and returns UPCOMING rows. This distinguishes a drafted fantasy league from an NBA season with observed performances.

Once games can be observed, live logs use `data/lockin.sqlite3`. The first refresh fetches the season, subsequent daily refreshes query from the last saved game minus seven days, and a full refresh every seven days reconciles older corrections. Upserts key on season/game/player. A process lock serializes refreshes; a transaction commits observations and freshness together. A failed or unexpectedly empty refresh retains previous rows and does not advance freshness. Multiple league analyses reuse the same daily data. Statistics and schedule errors are independent: missing statistics preserve the calendar and roster; missing schedules preserve observed scores but never establish a zero remaining-game count. The live prior uses older observed season data. The fixture provider never requests NBA data.

The Sleeper schedule feed is a public read-only endpoint used by this adapter, outside the core v1 league API. Its schema can change; invalid/empty/wrong-season responses fail closed. It currently provides dates and opponents, not tip-off times. Week views follow the model's Monday–Sunday convention; before opening night, the visible grid previews the opening week while the analysis cutoff stays unchanged.

## Data contracts

Normalized game frames require valid `GAME_DATE` and finite, nonnegative PTS, REB, AST, STL, BLK, TOV, and FG3M. Other shooting fields are added as zero if absent. MIN, when present, is parsed from numeric values or minute/second strings and validated. IDs, source metadata, and DD/TD/PTS40/PTS50 are retained.

Decision results include player identity, lineup slot/order, NBA team, live injury label, status, optional decision/score, observed history, warnings, and weekly schedule information. `schedule_state` distinguishes a verified off day from unknown data; `week_games` carries date, opponent, home/away, status, and observed FP only. Replay scores never appear beyond the observation cutoff. Suffix normalization and active-player preference resolve Sleeper names such as Tim Hardaway and Wendell Carter without selecting a retired relative. Incomplete results have `decision: null`; consumers must not infer WAIT or LOCK from absent fields.

| Status | Meaning |
| --- | --- |
| `UPCOMING` | No regular-season game has entered the observation cutoff yet; show schedule, issue no decision |
| `LOCK`, `WAIT` | An actionable model preference with usable inputs |
| `SCHEDULE_UNAVAILABLE` | Remaining opportunities cannot be established |
| `DATA_UNAVAILABLE` | Missing or invalid game/model inputs |
| `SCORING_INCOMPLETE` | League rules require unavailable stat fields; FP is partial |
| `UNRESOLVED` | Player identity could not be mapped |
| `NO_GAME` | No eligible completed performance this week |
| `NO_HISTORY` | No observed history for the player |
| `STALE` | Saved live recommendations require refresh |
| `BANKED` | User kept a fixed practice score |
| `PRE_DRAFT` / `DRAFTING` | League exists but is not ready for live recommendations |
| `LEAGUE_COMPLETE` | Imported league has ended its season |

## Persistence

| Path | Contents |
| --- | --- |
| `config.local.yaml` | Personal teams, scoring, notification addresses, Sleeper connection |
| `data/lockin.sqlite3` | Permanent observations and successful per-season refresh metadata |
| `state/publication.json` | Publication completion, pending commit, retry state |
| `data/cache/http/` | Response files, host cooldowns, request lock |
| `data/cache/archive/` | Raw Parquet downloads and immutable source revision |
| `data/cache/portraits/` | Cached player headshots |
| `data/fixtures/2025-26/` | Validated normalized tables and manifest |
| `data/fixture-manifest.json` | Shareable provenance without raw data or personal settings |
| `state/` | Saved reports, import metadata, delivery/pickup ledgers, credential guard |

All personal/generated paths are ignored by Git. A saved report is distinct from the response cache; showing old information as stale does not authorize a live fetch.

## Remaining boundaries

Snapshot writes are atomic, but roster configuration does not yet use a cross-process transaction lock. One local dashboard process is the intended editing workflow. Background job state lives in memory, so restarting the server loses job-status polling; completed config/report files remain on disk.

## Static publication boundary

`publication.py` runs on the Mac. It uses the saved local Sleeper configuration, refreshes the shared engine, and passes the result to `pages.py` for an explicit field allowlist. A fresh temporary Git repository uploads only generated website files to `gh-pages`, preserving branch history with a normal fast-forward push. GitHub Pages publishes that branch without running the model. No database, raw cache, credentials, or private configuration is uploaded. A publication ID is checked against the live `report.json` before the daily slot is marked successful.

The macOS LaunchAgent performs inexpensive due checks every 15 minutes, at login, and after a missed calendar event during sleep. Filesystem locking prevents overlapping publications. Failed uploads/deployments or partial data reports retain retry state with capped backoff. A previously uploaded report can be verified on the next check without refetching data. The original report generation timestamp controls the 26-hour browser expiry. See [Hosting](HOSTING.md).
