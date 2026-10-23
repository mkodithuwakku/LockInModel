# Implementation Runbook: Epic 3 — Database Centralization & Normalization

**Branch:** `architecture-v2` (merged to `main`)  
**Status:** Completed & verified (commit `f02ffc2`); production `data/lockin.sqlite3` migrated to v2 in place with a `data/lockin.sqlite3.v1.bak` backup.  
**Safety Boundary:** Must NOT overwrite or alter `data/lockin.sqlite3` directly. All changes must default to `data/experiment.sqlite3` or use the `LOCKIN_DB_PATH` environment variable.

---

## 1. Context & Architectural Problem

### Current State (v1 Inefficiencies)
1. **JSON Blob Redundancy:** `games` table in `data/lockin.sqlite3` stores box scores as raw JSON blobs in a `payload` text column. Every single row repeats strings like `"PLAYER_NAME"`, `"TEAM_ABBREVIATION"`, `"MATCHUP"`, and nested metadata.
2. **Missing SQL Queryability:** Python cannot query or filter on player statistics, opponents, or game outcomes via SQL. It must load every row for a season, run `json.loads` on each string, and assemble a pandas DataFrame in memory.
3. **Missing Dimension Tables:** No normalized `dim_players` or `dim_teams` tables exist. Player metadata is fragmented across JSON caches (`data/cache/`), Sleeper imports, and unindexed payload attributes.
4. **State Fragmentation:** Lock flags are kept in `state/locks.json` instead of SQL, requiring file-locking and manual JSON synchronization.

### Goal of Epic 3
Restructure SQLite into a normalized, high-performance relational schema with typed columns and dedicated dimension tables, while maintaining a **100% backward-compatible public API** for `GameStore.read()` and downstream modules (`engine.py`, `lineup.py`, etc.).

---

## 2. Target Relational Schema (v2)

All tables use SQLite Foreign Keys (`PRAGMA foreign_keys = ON;`).

```sql
-- Dimension: Teams
CREATE TABLE IF NOT EXISTS dim_teams (
    team_id TEXT PRIMARY KEY,           -- e.g. "1610612750" or Sleeper/NBA team ID
    abbreviation TEXT NOT NULL UNIQUE,  -- e.g. "MIN", "IND", "BOS"
    team_name TEXT NOT NULL             -- e.g. "Minnesota Timberwolves"
);

-- Dimension: Players
CREATE TABLE IF NOT EXISTS dim_players (
    player_id TEXT PRIMARY KEY,         -- NBA player ID or Sleeper fallback ID
    sleeper_id TEXT,                    -- Sleeper ID if mapped
    canonical_name TEXT NOT NULL,       -- Lowercase normalized (e.g. "anthony edwards")
    display_name TEXT NOT NULL,         -- Formatted display name (e.g. "Anthony Edwards")
    primary_position TEXT,              -- e.g. "PG", "SG", "SF", "PF", "C"
    birth_date TEXT                     -- YYYY-MM-DD (ISO)
);
CREATE INDEX IF NOT EXISTS idx_players_canonical ON dim_players(canonical_name);

-- Fact: Reconciled Game Logs (Strongly Typed Box Scores)
CREATE TABLE IF NOT EXISTS fact_game_logs (
    season TEXT NOT NULL,
    game_id TEXT NOT NULL,
    player_id TEXT NOT NULL REFERENCES dim_players(player_id),
    game_date TEXT NOT NULL,
    team_id TEXT REFERENCES dim_teams(team_id),
    opponent_id TEXT REFERENCES dim_teams(team_id),
    home INTEGER NOT NULL DEFAULT 0,    -- 1 = home, 0 = away
    wl TEXT,                            -- 'W' or 'L'
    min REAL NOT NULL DEFAULT 0.0,
    pts INTEGER NOT NULL DEFAULT 0,
    reb INTEGER NOT NULL DEFAULT 0,
    ast INTEGER NOT NULL DEFAULT 0,
    stl INTEGER NOT NULL DEFAULT 0,
    blk INTEGER NOT NULL DEFAULT 0,
    tov INTEGER NOT NULL DEFAULT 0,
    fgm INTEGER NOT NULL DEFAULT 0,
    fga INTEGER NOT NULL DEFAULT 0,
    fg3m INTEGER NOT NULL DEFAULT 0,
    fg3a INTEGER NOT NULL DEFAULT 0,
    ftm INTEGER NOT NULL DEFAULT 0,
    fta INTEGER NOT NULL DEFAULT 0,
    oreb INTEGER NOT NULL DEFAULT 0,
    dreb INTEGER NOT NULL DEFAULT 0,
    pf INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (season, game_id, player_id)
);
CREATE INDEX IF NOT EXISTS idx_games_date ON fact_game_logs(game_date);
CREATE INDEX IF NOT EXISTS idx_games_player ON fact_game_logs(player_id, game_date);
CREATE INDEX IF NOT EXISTS idx_games_opponent ON fact_game_logs(opponent_id);

-- Fact: Pregame Forecast Snapshots (Retained from forecast_store)
CREATE TABLE IF NOT EXISTS fact_forecasts (
    formula_key TEXT NOT NULL,
    game_date TEXT NOT NULL,
    player_id TEXT NOT NULL REFERENCES dim_players(player_id),
    projected_fp REAL NOT NULL,
    source TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    PRIMARY KEY (formula_key, game_date, player_id)
);

-- Fact: Pinned Starters (Brought into SQLite from locks.json)
CREATE TABLE IF NOT EXISTS fact_locks (
    league_id TEXT NOT NULL,
    schedule_week INTEGER NOT NULL,
    player_id TEXT NOT NULL REFERENCES dim_players(player_id),
    roster_slot TEXT NOT NULL,
    slot_index INTEGER NOT NULL,
    locked_fp REAL,
    game_date TEXT,
    locked_at TEXT NOT NULL,
    PRIMARY KEY (league_id, schedule_week, player_id)
);

-- Dimension: Sync Freshness Status
CREATE TABLE IF NOT EXISTS dim_refreshes (
    season TEXT PRIMARY KEY,
    refreshed_on TEXT NOT NULL,
    full_on TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
```

---

## 3. Strict File Boundaries (What to Touch vs What NOT to Touch)

### Files to Modify / Create
1. `game_store.py`:
   - Support `LOCKIN_DB_PATH` environment variable (defaults to `data/lockin.sqlite3` if unset, or `data/experiment.sqlite3` in test/dev).
   - Implement the new v2 relational DDL.
   - Update `read(season)`: Execute an efficient `JOIN` between `fact_game_logs`, `dim_players`, and `dim_teams`, reconstructing the DataFrame with expected uppercase column headers (`GAME_ID`, `PLAYER_ID`, `PLAYER_NAME`, `GAME_DATE`, `TEAM_ABBREVIATION`, `PTS`, etc.).
   - Update `upsert_games()` / `refresh()`: Ingest normalized rows into `dim_players`, `dim_teams`, and `fact_game_logs`.
2. `scripts/migrate_v2_db.py` (New):
   - Standalone migration script that reads the legacy `games` JSON payloads from a source SQLite file, extracts unique players/teams, and writes them into the normalized v2 schema.
3. `tests/test_game_store.py`:
   - Add unit tests verifying schema integrity, foreign keys, and that `GameStore.read()` produces an identical DataFrame structure to legacy v1.

### Files NOT to Modify
- Do NOT touch `model.py`, `decide.py`, or `lineup.py` yet. They interact with `GameStore` via DataFrames and will naturally work if `GameStore.read()` preserves its contract.
- Do NOT alter `publication.py` or production scheduler scripts until migration is validated.

---

## 4. Step-by-Step Implementation Plan

### Step 1: Database Path Isolation & Environment Override
In `game_store.py`:
```python
import os
DEFAULT_DB_PATH = Path(os.environ.get("LOCKIN_DB_PATH", ROOT / "data/lockin.sqlite3"))
```
When running tests or migrations, set `LOCKIN_DB_PATH="data/experiment.sqlite3"`.

### Step 2: DDL Initialization & Table Migration
In `GameStore.__init__`:
- Enable foreign keys: `db.execute("PRAGMA foreign_keys = ON;")`.
- Create `dim_teams`, `dim_players`, `fact_game_logs`, `dim_refreshes`.
- Provide a legacy detection helper: if table `games` with column `payload` exists, mark as `legacy_mode=True`.

### Step 3: Backward-Compatible `read(season)`
In `GameStore.read(season)`:
- Query:
  ```sql
  SELECT
      g.game_id AS GAME_ID,
      g.player_id AS PLAYER_ID,
      p.display_name AS PLAYER_NAME,
      g.game_date AS GAME_DATE,
      t.abbreviation AS TEAM_ABBREVIATION,
      opp.abbreviation AS MATCHUP,
      g.wl AS WL,
      g.min AS MIN,
      g.pts AS PTS,
      g.reb AS REB,
      g.ast AS AST,
      g.stl AS STL,
      g.blk AS BLK,
      g.tov AS TOV,
      g.fgm AS FGM,
      g.fga AS FGA,
      g.fg3m AS FG3M,
      g.fg3a AS FG3A,
      g.ftm AS FTM,
      g.fta AS FTA,
      g.oreb AS OREB,
      g.dreb AS DREB,
      g.pf AS PF
  FROM fact_game_logs g
  JOIN dim_players p ON g.player_id = p.player_id
  LEFT JOIN dim_teams t ON g.team_id = t.team_id
  LEFT JOIN dim_teams opp ON g.opponent_id = opp.team_id
  WHERE g.season = ?
  ORDER BY g.game_date, g.game_id, g.player_id
  ```
- Return `parse_dates(df)`.

### Step 4: Migration Tool (`scripts/migrate_v2_db.py`)
Create a CLI migration tool:
```bash
python scripts/migrate_v2_db.py --src data/lockin.sqlite3 --dest data/experiment.sqlite3
```
Verification checks in script:
1. Count of unique player-games in v1 equals row count in `fact_game_logs`.
2. Sum of `PTS`, `REB`, `AST` matches between v1 and v2.
3. Checksums or zero null foreign keys.

---

## 5. Verification & Acceptance Criteria

1. **Isolation Check:** Verify `data/lockin.sqlite3` is never modified during tests.
2. **Schema Verification:** Query `sqlite_master` in `test_game_store.py` to confirm typed tables exist and indexes are present.
3. **Data Integrity Test:** Run `GameStore.read()` on migrated data and compare column-by-column against legacy outputs.
4. **All Existing Tests Pass:**
   ```bash
   .venv/bin/python -m pytest -q
   .venv/bin/python -m black --check *.py tests
   node --test tests/*.test.cjs
   ```
