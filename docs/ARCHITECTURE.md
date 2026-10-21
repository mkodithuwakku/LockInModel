# Architecture and data contracts

## Modules

| Module | Responsibility |
| --- | --- |
| `app.py` | Flask routes, same-origin protection, background refresh jobs, dashboard cache |
| `web/` | Responsive interface, team navigation, player details, roster editing, import UI |
| `web/insights.js` | Pure observed-form calculations and sparklines from scored report history; shared by local and hosted views |
| `storage.py` | Canonical YAML loading/validation; atomic JSON/YAML writes |
| `simulation.py` | Persistent morning/night replay, isolated practice roster snapshot, revision checks, banked scores |
| `engine.py` | Shared dashboard/report orchestration and per-input decision reuse |
| `providers.py` | Explicit fixture/live input policies |
| `fetch_data.py` | NBA adapters, name matching, strict normalization, dates, bonuses |
| `game_store.py` | SQLite player-game history, daily overlap upserts, weekly full reconciliation |
| `publication.py` | Local static publication, deployment verification, retry ledger, macOS wake catch-up |
| `transport.py` | Persistent response cache, request serialization/pacing, cooldown circuit |
| `scoring.py` | Validated league weights, generic milestone bonuses, foul/rebound fallback policy, FP calculation |
| `pages.py` | Live report generation, public field allowlist, static asset export |
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

Normalized game frames require valid `GAME_DATE` and finite, nonnegative PTS, REB, AST, STL, BLK, TOV, and FG3M. Other shooting fields are added as zero if absent and recorded as imputed so they cannot silently satisfy a required weight. MIN, when present, is parsed from numeric values or minute/second strings and validated. IDs, source metadata, and DD/TD/PTS40/PTS50 are retained. Scoring recomputes double/triple-double and configurable milestone indicators from base observations. `scoring_notes` describes intentionally omitted fouls and total-rebound approximations; these differ from unsupported nonzero rules that produce `SCORING_INCOMPLETE`.

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

### Observed team form

The Recent form panel consumes existing `history` records, bounded by `observation_cutoff`; it makes no additional requests. It sorts players by the arithmetic mean of up to five latest observed scores, preserving each player's roster index for detail links. A change value requires ten valid observations and compares two disjoint five-game means. Missing history is distinct from zero FP. Sparklines have individual vertical scales and describe shape rather than absolute comparisons between players. Stale/failed data is labeled saved history, with remaining-game labels suppressed; the panel does not authorize recommendations.

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

### Shared game store

| SQLite table | Key | Stored fields |
| --- | --- | --- |
| `games` | `(season, game_id, player_id)` | `game_date`, JSON observation `payload` |
| `refreshes` | `season` | `refreshed_on`, `full_on`, UTC `fetched_at` |

The store retains observations rather than a separate copy of fantasy points per league. Every league can rescore the same history with its own formula, including newly configured milestones. A refresh validates the fetched batch before writing. The game upserts and successful-refresh metadata share one SQLite transaction; a process-level file lock serializes the larger read/fetch/write operation. An already successful calendar-day refresh is reused by the CLI, dashboard, and publisher.

This is an upsert history, not an immutable event log: corrected records replace their earlier payload. Full reconciliation updates returned records but does not delete stored records absent from a response. Failed refreshes preserve the database, while the provider reports the failure and withholds performance recommendations rather than presenting retained rows as a fresh download. Historical replay stays in separate checksummed Parquet files, independent of these mutable live records.

## Remaining boundaries

Snapshot writes are atomic, but roster configuration does not yet use a cross-process transaction lock. One local dashboard process is the intended editing workflow. Background job state lives in memory, so restarting the server loses job-status polling; completed config/report files remain on disk.

## Static publication boundary

`publication.py` runs on the Mac. It uses the saved local Sleeper configuration, refreshes the shared engine, and passes the result to `pages.py` for an explicit field allowlist. A fresh temporary Git repository uploads only generated website files to `gh-pages`, preserving branch history with a normal fast-forward push. GitHub Pages publishes that branch without running the model. No database, raw cache, credentials, or private configuration is uploaded. A publication ID is checked against the live `report.json` before the daily slot is marked successful.

The macOS LaunchAgent performs inexpensive due checks every 15 minutes, at login, and after a missed calendar event during sleep. Filesystem locking prevents overlapping publications. Failed uploads/deployments or partial data reports retain retry state with capped backoff. A previously uploaded report can be verified on the next check without refetching data. The original report generation timestamp controls the 26-hour browser expiry; a previous fantasy week expires at the next Monday even if younger than 26 hours. See [Hosting](HOSTING.md).

Source and publication have separate lifecycles. A `main` push or pull request runs `.github/workflows/tests.yml`; it does not generate a report or deploy source files. The local publisher reads the current checkout and updates only `gh-pages`. GitHub's managed Pages build deploys that static branch. Local configuration, SQLite transactions, report files, Git push, and Pages deployment are not one transaction; the publication ledger handles retry and confirmation between those stages.

## Daily lineup data flow

Sleeper sync now persists the full `roster_positions` array, preserving unoccupied and repeated slots. `engine.build_dashboard()` resolves roster identities and verified weekly schedules, projects only roster players from pre-day history in `lineup.py`, and attaches `recommended_lineup` to each team. Projection work is cached within a report for matching roster/scoring combinations. The exact assignment solver is independent of the provider and UI; it supports custom combinations of standard basketball slots without league-specific code.

`LiveProvider.lineup_history()` optionally reads the previous season from the same SQLite store; if that season is empty, a checksum-verified existing fixture can supply the labeled fallback. It makes no new API requests and does not change lock-model priors. Unknown/missing data and failed refreshes withhold or explicitly mark partial lineups. Test Week's pregame preview excludes same-day scores, and is suppressed once a practice score is banked.

The nested `recommended_lineup` contract contains date, status/reason, total FP, filled/eligible/missing counts, ordered slots, and unselected players with reasons. `pages.public_report()` explicitly allowlists both the summary and nested player fields; private configuration is never copied wholesale. Flask and the browser clear daily selections when the Edmonton date changes, independently of report expiry. `web/pages.js` is loaded on local and hosted pages so both use the same browser date policy. Open tabs recheck on visibility changes and every minute.

The responsive card shares the right rail with Recent form, appears above the roster on phones, and places both panels side by side at tablet widths. Player links reuse canonical roster indexes. No API route, external database, remote Mac trigger, or automatic Sleeper action is added.

## Full-roster forecasts and chart coverage

`projections.py` fetches the current-season Sleeper `/projections/nba/<season>` feed once per live report, using the existing six-hour HTTP cache and cooldown handling. It validates season/type/category/provider and finite per-game components, divides season totals by `gp` if needed, converts seconds to minutes, and derives OREB from REB minus DREB when available. Forecasts are never inserted into SQLite observation history. The API is currently served by Sleeper but is outside its documented v1 league API; schema validation and genuine failure alerts remain necessary.

Every roster result now has an independent `projection` object, including bench, out, and off-day players. Current-season observations win; a validated current forecast replaces older-season baselines. A rookie can use the imported Sleeper ID without inventing an NBA ID or making a broken portrait request. Existing weekly locks still require observed eligible performances. Independently valid forecasts can support a daily plan during a game-log outage; stale retained game logs do not masquerade as fresh forecasts.

For players with no current history, verified older observations populate history charts and carry `history_source: prior_season`. These games are scored under the selected league's rules; forecast rows never enter those charts. Players with no NBA observations retain a forecast and an honest empty history state. `pages.py` allowlists the nested projection summary and stat keys separately. The UI renders source/date and projected FP plus PTS/REB/AST on every row, with a full projected box score in player details.

Approved foul omissions and rebound approximations live in `scoring_notes` under Scoring method. They no longer create operational alerts or a warning count. Unknown scoring rules and actual provider failures remain alerts.


### Team identity

Sleeper import stores `team_avatar_url`, preferring the league user's
`metadata.avatar`, then the profile/account avatar. Avatar IDs resolve to Sleeper's
thumbnail CDN; only HTTPS `sleepercdn.com/uploads/` or `/avatars/` URLs are accepted.
The field passes through both full and unavailable roster reports and the public
export allowlist. Browsers load it directly with no referrer; failed or absent
pictures fall back to initials. The existing daily sync updates changed photos.
This adds no image database or new scheduled job. The inline LI emblem and matching
SVG favicon are local assets; the charcoal/plum palette preserves the responsive
layout and text labels for every status.
