# Agent Reference: Architecture & Data Map

This document is a high-density reference for agents navigating the backend, data stores, scoring algorithms, and data contracts. Read this before modifying engine, storage, or modeling logic.

---

## 1. Module Responsibility Map

| Module | Core Responsibility | Key Functions / Classes |
| :--- | :--- | :--- |
| `engine.py` | Orchestrates dashboard generation, coordinates providers, caches reports per team/scoring | `build_dashboard()`, `roster_dashboard()`, `today()` |
| `providers.py` | Distinguishes live NBA/Sleeper feeds (`LiveProvider`) from immutable test fixtures (`FixtureProvider`) | `LiveProvider`, `FixtureProvider` |
| `scoring.py` | Computes fantasy points from box scores; validates weights, recomputes DD/TD/threshold bonuses; foul/rebound fallbacks | `add_fantasy_points()`, `effective_weights()`, `milestone()` |
| `fetch_data.py` | Player identity matching, name/suffix normalization, dates, NBA Stats endpoints, stat validation | `normalize_stats_for_scoring()`, `canonical_name()`, `player_directory()` |
| `decide.py` | Evaluates whether to LOCK or WAIT for a player's latest score in the fantasy week | `per_player_week_decision()`, `evaluate_player_lock()` |
| `model.py` | Recency-weighted baseline (exponential decay), career/prior shrinkage, variance floors, normal beat probability, rarity adjustment | `rolling_baseline()`, `probability_future_beats_current()`, `rarity_score()` |
| `season_history.py` | Blends prior-season games into sparse current-season projections and lock baselines (default 10-game window) | `blend_seasons()` |
| `lineup.py` | Daily pregame forecasts and Hungarian algorithm optimizer for maximum-weight positional lineup assignment; locked players pin to their synced slot before the solver sees the pool; leftover slots fill with idle roster players as zero-projection off-day placeholders | `recommend_lineup()`, `project_players()`, `active_slots()`, `lock_match()`, `locked_score()` |
| `projections.py` | Validates and parses Sleeper/RotoWire per-game external forecasts; derives Poisson-approximated milestone expectations | `fetch_forecasts()`, `parse_forecasts()`, `forecast_profile()` |
| `game_store.py` | Local SQLite player-game store; daily overlap upserts (7-day window) and weekly full-season reconciliation | `GameStore`, `games` table, `refresh_status` table |
| `forecast_store.py` | SQLite pregame forecast snapshots by formula fingerprint, date, and player ID | `ForecastStore`, `formula_key()`, `forecast_snapshots` table |
| `daily_badges.py` | Computes 15 NBA-wide stat leader badges and 4 league-scored fantasy leader badges for yesterday's games | `previous_night_badges()`, `fantasy_night_badges()` |
| `badge_awards.py` | Computes 15 single-game stat milestones, 10 contextual awards (streaks, age, outcome, assist-to-turnover margin) | `raw_awards()`, `fantasy_awards()`, `MILESTONES`, `EXTRA_KEYS` |
| `badge_store.py` | Manages season badge ledger in SQLite; idempotency, streak recalculation, formula isolation, and aggregate counts | `BadgeStore`, `badge_days` and `badge_awards` tables |
| `season_review.py` | Aggregates current-roster observed season production, box-score sums, weekly FP/appearance, and key player highlights | `season_review()` |
| `pickups.py` | Screens unrostered waiver players using 5 recent vs 8–20 baseline games; consistency, sustainability, and roster compatibility; schedule-aware add/drop swap suggestion weighs this week plus a next-week horizon | `find_pickups()`, `analyze_player()`, `available_player_directory()`, `suggest_swap()` |
| `sleeper.py` | Read-only import of Sleeper leagues, teams, rosters, scoring settings, and ownership metadata | `import_sleeper()`, `fetch_user_leagues()` |
| `sleeper_stats.py` | Validated Sleeper/Sportradar fallback box scores when NBA Stats fails or misses recent finals | `parse_games()`, `fetch_sleeper_games()` |
| `schedule.py` | Full-season regular schedule cache; determines remaining weekly game opportunities | `season_schedule()`, `remaining_games()` |
| `storage.py` | Loads canonical `config.local.yaml` (falling back to `config.yaml`); atomic JSON and YAML writes; weekly lock-flag document for `state/locks.json` | `load_cfg()`, `save_cfg()`, `write_json()`, `load_locks()`, `save_locks()`, `locks_for_league()`, `apply_lock()` |
| `simulation.py` | Manages offline Test Week simulator state, phase transitions (morning/night), banked scores, and revisions | `load_test_week()`, `advance_night()`, `bank_score()` |
| `publication.py` | Local daily scheduled exporter to `gh-pages`; LaunchAgent installation, retry ledger, deployment confirmation; fast-forwards `main` before analysis to absorb phone lock commits | `publish_due()`, `run_publication()`, `install_agent()`, `sync_remote_locks()` |
| `pages.py` | Filters dashboard data to public allowlisted fields; exports static JSON, HTML, CSS, JS, and image assets | `export_site()`, `refresh_report()`, `public_report()` |
| `transport.py` | Rate-limited HTTP client with on-disk response caching, host pacing, and persistent failure cooldowns | `HTTP`, `CachedHTTP`, `DataUnavailable` |
| `app.py` | Local Flask HTTP server; CSRF token validation, loopback restriction, background job worker | `/api/bootstrap`, `/api/dashboard`, `/api/test-week`, `/api/roster`, `/api/sync`, `/api/refresh`, `/api/lock` |
| `api/lock.mts` | Optional Vercel serverless bridge: validates `x-lockin-passcode`, commits `state/locks.json` to `main` via the GitHub Contents API, retries conflicts | `handler()` |
| `shared/locks-core.mjs` | Shared pure lock-document logic for the endpoint (payload validation, lock/unlock, week expiry); kept outside `api/` so Vercel does not route it | `validatePayload()`, `applyLock()`, `emptyDocument()` |
| `web/app.js` | Frontend presentation controller; routing, dialogs, team switching, rendering, player modals, dismiss handlers, lock toggle with optimistic POST and passcode prompt | DOM rendering, event listeners, `toggleLock()`, `postLock()` |
| `web/insights.js` | Pure client-side calculations: recent form deltas, sparklines, performance colour baselines, badge formatting, roster sheet order, client-side lineup re-derivation (locks + placeholder fill) | `rosterSheet()`, `repinLineup()`, `performanceScore()`, `performanceBaseline()`, `formScore()` |

---

## 2. Persistence & SQLite Data Model

SQLite database location: `data/lockin.sqlite3` (managed by `GameStore`, `ForecastStore`, `BadgeStore`).

### Tables
1. **`games`** (`game_store.py`):
   - Key: `(season, game_id, player_id)`
   - Stores: Observed regular-season box scores (`PTS`, `REB`, `AST`, `STL`, `BLK`, `TOV`, `MIN`, `FGM`, `FGA`, `FG3M`, `FG3A`, `FTM`, `FTA`, `WL`, etc.).
   - Ingestion: Reconciled upsert. Final games only.
2. **`refresh_status`** (`game_store.py`):
   - Key: `season`
   - Stores: Last successful refresh timestamp.
3. **`forecast_snapshots`** (`forecast_store.py`):
   - Key: `(formula_key, game_date, player_id)`
   - Stores: Pregame projected fantasy points saved before games tip off. Used for above/below expectation badges.
4. **`badge_days`** (`badge_store.py`):
   - Key: `(formula_key, game_date)`
   - Stores: Hash fingerprint of observed games on that date, rules version, and processing status. Skips unchanged nights; recomputes on corrections.
5. **`badge_awards`** (`badge_store.py`):
   - Key: `(formula_key, game_date, player_id, badge_key)`
   - Stores: Individual earned badges, rank, value, tied status, and detail metadata.

### Configuration & State Files
- `config.local.yaml`: Authoritative user configuration (ignored in git).
- `config.yaml`: Checked-in default configuration fallback.
- `state/publication.json`: Publication ledger (published commit, daily completion slot, pending deployment, retry counters).
- `state/test-week.json`: Current state of the offline practice simulator (clock, revision, banked scores, roster edits).
- `state/email-delivery.json`: Delivery ledger suppressing duplicate daily emails.
- `state/locks.json`: Manager-reported Sleeper lock flags keyed by league and matchup week — the one `state/` file intentionally committed, shared between the phone write path and the Mac publication.
- `data/fixtures/2025-26/`: Checksum-verified Parquet tables for offline Test Week (`games.parquet`, `schedule.parquet`, `priors.parquet`).

---

## 3. Data Flow & Execution Boundaries

```
[External Sources]
   ├─ NBA Stats API (or Sleeper/Sportradar fallback) ──► GameStore (SQLite: games)
   ├─ Sleeper Schedule & Roster API ─────────────────► Schedule cache & config.local.yaml
   └─ Sleeper / RotoWire Projections ────────────────► ForecastStore (SQLite: forecast_snapshots)
            │
[Analysis Engine] (`engine.py`)
   ├─ Provider (`providers.py`): LiveProvider or FixtureProvider
   ├─ Filter: Observations strictly <= decision cutoff (NO future data leakage)
   ├─ Blend: `season_history.blend_seasons()` fills sparse histories (<10 games) with prior season
   ├─ Scoring: `scoring.add_fantasy_points()` applies league weights & derived bonuses
   ├─ Weekly Decisions: `decide.py` + `model.py` (LOCK / WAIT / REVIEW)
   ├─ Daily Lineup: `lineup.py` Hungarian algorithm maximizes projected FP across league slots
   ├─ Daily Badges: `daily_badges.py` + `badge_awards.py` evaluate yesterday's performances
   ├─ Season Badges: `badge_store.py` updates cumulative season awards
   ├─ Season Review: `season_review.py` aggregates full current-roster season production
   └─ Waivers: `pickups.py` screens unrostered rising players
            │
[Delivery Boundaries]
   ├─ Local Flask UI (`app.py`, `127.0.0.1:8765`): Interactive practice, roster editing, Sleeper sync
   ├─ Static Web Export (`pages.py`, `publication.py`): Allowlisted public fields -> gh-pages branch
   └─ Local CLI / Email (`main.py`, `notify.py`): Terminal report and optional SMTP email
```

---

## 4. Key Modeling Heuristics

1. **Lock/Wait Decision** (`decide.py`, `model.py`):
   - Computes weighted recent mean and standard deviation with exponential decay (default `d=0.92`).
   - Normal CDF calculates $P(\text{future score} > \text{current score})$.
   - Adjusts for stat rarity z-scores ($\ge 1.75$), small sample size ($<3$ games), and remaining schedule opportunities.
   - Outputs a heuristic score in $[0, 1]$. Value $\ge 0.5$ triggers `LOCK`, else `WAIT`.
2. **Hungarian Positional Lineup Optimizer** (`lineup.py`):
   - Matches eligible active slots (`PG`, `SG`, `SF`, `PF`, `C`, `G`, `F`, `UTIL`) to available players.
   - Excludes injured (`OUT`, `IR`, `INACTIVE`) and off-day players.
   - Exact maximum-weight assignment; runtime $O(S^2(P+S))$.
3. **Daily Badges** (44 total indicators):
   - 15 raw box-score leader badges (`sniper`, `fire`, `boards`, `bricks`, `thief`, `rejection`, `runner`, `dime`, `sandwich`, `merchant`, `heartbreak`, `shield`, `creator`, `coffee`, `magician`).
   - 4 league-scored fantasy badges (`overachiever`, `underachiever`, `efficient`, `inefficient`).
   - 15 single-game stat milestones (points: 30–70; assists: 10–20; rebounds: 10–20; threes: 5, 10; steals: 10; blocks: 10). Only highest tier per stat awarded.
   - 10 contextual awards (Butterfingers, 3-game heater/cold spell, winning/losing MVP, along for the ride, home hero, away villain, Unction $\ge 32$, Young Boys $\le 23$).
