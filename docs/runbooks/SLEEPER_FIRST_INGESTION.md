# Runbook: Sleeper-first ingestion with NBA API as preferred source

**Goal:** Daily refresh must never fail just because `stats.nba.com` is unreachable.
Sleeper stats (`api.sleeper.com/stats`) is the guaranteed floor; the NBA Stats API
stays the preferred source when reachable. All NBA game-log ingestion uses bulk
endpoints only — the per-player `PlayerGameLog` endpoint is removed from the live path.

**Why:** On 2026-11-06 the NBA Stats API began tarpitting this deployment's IP
(instant 403 on the domain root, connection hang on API paths). 48h+ blocks are
documented behavior; the per-player endpoint multiplied request volume dozens of
times over what bulk endpoints need.

## Invariants (do not violate)

- Never fabricate stats. Missing columns propagate via `df.attrs["imputed_stats"]`
  and display as blank/`None`, not zero.
- Sleeper-first data must still reconcile: `sleeper_stats.parse_games` raises
  `DataUnavailable` if box scores don't match schedule points/minutes — keep that.
- `provider.stats_error` semantics stay: partial data is labeled, never swapped silently.
- Unit tests stay offline (`tests/conftest.py` blocks sockets); mock all payloads.
- No per-player game-log endpoint calls anywhere in the live/replay path.

## File routing (read these, not whole files)

| File | Lines | What it does |
|---|---|---|
| `fetch_data.py` | 75–97 | `endpoint_frame()` — shared stats.nba.com wrapper, `pace=3`, raises `DataUnavailable` |
| `fetch_data.py` | ~110–120 | `get_player_logs()` — the per-player `PlayerGameLog` call to eliminate |
| `fetch_data.py` | ~255–272 | Bulk `PlayerGameLogs` inside `GameStore().refresh` — reuse this pattern |
| `fetch_data.py` | ~274–281 | `bulk_team_logs()` — team-level `LeagueGameLog` |
| `fetch_data.py` | ~156–165 | `normalize_stats_for_scoring()` — sets `imputed_stats` for absent columns |
| `sleeper_stats.py` | 55–120 | `parse_games()` — builds NBA-schema rows from Sleeper payload, `SOURCE="Sleeper / Sportradar"`, validates vs schedule |
| `sleeper_stats.py` | ~122–140 | `completed_logs(calendar, reference)` — weekly Sleeper fetch → `GameStore().refresh` |
| `scoring.py` | ~70–90 | Missing-stat handling; `OREB`/`DREB` weights split evenly onto `REB` when splits absent |
| `scoring.py` | ~109–120 | `add_fantasy_points()` — skips `imputed_stats` columns |
| `providers.py` | ~81–133 | `LiveProvider`: `stats_error`, `live_logs()` already calls `completed_logs` on failure |
| `game_store.py` | `refresh()` | Overlap/full-reconcile ingest; the single write path — both sources feed through it |
| `engine.py` | ~220 | `fallback = provider.lineup_history()` — prior-season bootstrap for `<10` games |
| `publication.py` | ~307 | Publish flow: `sync_remote_locks` → `refresh_report` |

## Phase A — bulk-only NBA ingestion

1. `rg -n 'get_player_logs|playergamelog\.PlayerGameLog'` across `*.py`. Every live-path
   call site must instead pull the relevant slice from the bulk frame
   (`PlayerGameLogs` for players, `LeagueGameLog` for teams) and filter by
   `PLAYER_ID` locally — never hit the endpoint.
2. `get_player_logs` may keep its signature as a filter over a bulk frame (tests
   assert its shape) or be deleted if unused; callers needing career history use
   `GameStore`/`provider.priors` rather than fresh per-player requests.
3. Keep `endpoint_frame` — it's the only place stats.nba.com is touched; bulk
   endpoints flow through it unchanged (pace, ttl, error shape).
4. Result: **≤2 NBA API requests per refresh** (one `PlayerGameLogs` since last
   saved date + optional `LeagueGameLog` for team-level data). Weekly full-season
   reconcile is still 1 request.

## Phase B — Sleeper-first fallback & missing OREB/DREB

1. In `providers.py` `live_logs()`: when the stats fetch raises `DataUnavailable`
   or times out, fall back to `sleeper_stats.completed_logs(calendar, reference)`
   and return its frame with `SOURCE` intact. There is already a partial version
   of this at ~line 122 — generalize it so **any** stats failure degrades, not
   only specific exceptions. Set `self.stats_error` to a short reason string so
   the report labels it.
2. Column mapping gap: Sleeper rows lack `PLUS_MINUS`, `OREB`, `DREB` (verify the
   actual payload keys against `STATS` in `game_store.py`). After
   `normalize_stats_for_scoring`, ensure absent columns are recorded in
   `df.attrs["imputed_stats"]` — same mechanism `normalize_stats_for_scoring`
   uses at fetch_data.py ~163.
3. OREB/DREB accuracy: `scoring.py` (~85–89) already splits combined OREB+DREB
   weight evenly onto `REB` when splits are missing. Verify this applies in
   **every** path that calls `add_fantasy_points` (projection baselines in
   `lineup.project_players`, lock baselines in `decide.rolling_baseline`, film
   audit, season review). If a league weights OREB ≠ DREB, document that the
   split is an approximation — do not silently merge into REB twice.
4. `GameStore` rows written from Sleeper keep `SOURCE="Sleeper / Sportradar"`;
   NBA-sourced rows keep the NBA source. The mixed-source DB is intended — the
   Ridge model's `features.py` uses pace/DefRtg computed from ordinary box-score
   columns, all of which Sleeper provides, so opponent-aware projections degrade
   only on the exotic columns.
5. Publishing: a Sleeper-sourced refresh is a **successful** report (status `ok`),
   not a failure. Notes about approximated OREB/DREB go in `scoring_notes`, not alerts.

## Phase C — throttle hygiene

- Keep `pace=3` minimum on stats.nba.com; a daily bulk job costs 1–2 requests.
- Confirm `transport.HTTP` retry logic doesn't hammer a tarpitted host — a hung
  request is one timeout, then the fallback fires; no tight retry loop.
- Sleeper stats pacing stays `pace=3`.

## Test plan

- `tests/test_sleeper_stats.py` — extend: column coverage mapping, `imputed_stats`
  propagation, reconcile-failure still raises.
- `tests/test_integration.py` — add: `live_logs` falls back to Sleeper on
  `DataUnavailable`, returns reconciled frame, sets `stats_error`; no fallback
  when stats succeed.
- `tests/test_core.py` / `test_model_ml.py` — assert OREB/DREB weight split on
  REB-only frames keeps FP within tolerance for leagues weighting them.
- `rg -n 'PlayerGameLog'` must return zero live-path call sites.
- Verify: `.venv/bin/python -m pytest -q` · `.venv/bin/python -m black --check *.py tests` · `node --test tests/*.test.cjs`

## Acceptance

- A refresh with stats.nba.com unreachable produces a full `ok` report built from
  Sleeper stats, with OREB/DREB labeled approximated in `scoring_notes`.
- With the API reachable, identical-season reports continue to prefer NBA data.
- Total stats.nba.com requests per daily refresh: ≤2.
- All suites green; docs `README.md` and `docs/HOSTING.md` updated.
