"""Permanent local player-game history, shared by every live league.

Refreshes append new games and upsert corrections by season/game/player. A rolling
seven-day overlap catches recent corrections; weekly full reads reconcile older
ones. Failed requests never advance freshness or remove existing observations.

v2 keeps normalized dimensions (dim_teams, dim_players) and typed box scores
(fact_game_logs) instead of JSON payloads. Databases that still hold the legacy
`games` payload table keep reading it until a refresh or the migration script
moves that season's rows into the fact table.
"""

from contextlib import contextmanager
import datetime as dt
import fcntl
import json
import math
import os
from pathlib import Path
import sqlite3

import pandas as pd
from storage import ROOT
from transport import DataUnavailable

STATS = (
    "PTS",
    "REB",
    "AST",
    "STL",
    "BLK",
    "TOV",
    "FGM",
    "FGA",
    "FG3M",
    "FG3A",
    "FTM",
    "FTA",
    "OREB",
    "DREB",
    "PF",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS dim_teams (
    team_id TEXT PRIMARY KEY,
    abbreviation TEXT NOT NULL UNIQUE,
    team_name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dim_players (
    player_id TEXT PRIMARY KEY,
    sleeper_id TEXT,
    canonical_name TEXT NOT NULL,
    display_name TEXT NOT NULL,
    primary_position TEXT,
    birth_date TEXT
);
CREATE INDEX IF NOT EXISTS idx_players_canonical ON dim_players(canonical_name);
CREATE TABLE IF NOT EXISTS fact_game_logs (
    season TEXT NOT NULL,
    game_id TEXT NOT NULL,
    player_id TEXT NOT NULL REFERENCES dim_players(player_id),
    game_date TEXT NOT NULL,
    team_id TEXT REFERENCES dim_teams(team_id),
    opponent_id TEXT REFERENCES dim_teams(team_id),
    home INTEGER NOT NULL DEFAULT 0,
    wl TEXT,
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
    source TEXT,
    PRIMARY KEY (season, game_id, player_id)
);
CREATE INDEX IF NOT EXISTS idx_games_date ON fact_game_logs(game_date);
CREATE INDEX IF NOT EXISTS idx_games_player ON fact_game_logs(player_id, game_date);
CREATE INDEX IF NOT EXISTS idx_games_opponent ON fact_game_logs(opponent_id);
CREATE TABLE IF NOT EXISTS dim_refreshes (
    season TEXT PRIMARY KEY,
    refreshed_on TEXT NOT NULL,
    full_on TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
"""

READ_SQL = """
SELECT
    g.game_id AS GAME_ID,
    g.player_id AS PLAYER_ID,
    p.display_name AS PLAYER_NAME,
    g.game_date AS GAME_DATE,
    COALESCE(t.abbreviation, '') AS TEAM_ABBREVIATION,
    CASE
        WHEN t.abbreviation IS NULL OR opp.abbreviation IS NULL THEN ''
        ELSE t.abbreviation
            || CASE WHEN g.home THEN ' vs. ' ELSE ' @ ' END
            || opp.abbreviation
    END AS MATCHUP,
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
    g.pf AS PF,
    g.source AS SOURCE
FROM fact_game_logs g
JOIN dim_players p ON g.player_id = p.player_id
LEFT JOIN dim_teams t ON g.team_id = t.team_id
LEFT JOIN dim_teams opp ON g.opponent_id = opp.team_id
WHERE g.season = ?
ORDER BY g.game_date, g.game_id, g.player_id
"""

UPSERT_SQL = """
INSERT INTO fact_game_logs (
    season, game_id, player_id, game_date, team_id, opponent_id, home, wl, min,
    pts, reb, ast, stl, blk, tov, fgm, fga, fg3m, fg3a, ftm, fta, oreb, dreb, pf,
    source
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(season, game_id, player_id) DO UPDATE SET
    game_date=excluded.game_date,
    team_id=excluded.team_id,
    opponent_id=excluded.opponent_id,
    home=excluded.home,
    wl=excluded.wl,
    min=excluded.min,
    pts=excluded.pts,
    reb=excluded.reb,
    ast=excluded.ast,
    stl=excluded.stl,
    blk=excluded.blk,
    tov=excluded.tov,
    fgm=excluded.fgm,
    fga=excluded.fga,
    fg3m=excluded.fg3m,
    fg3a=excluded.fg3a,
    ftm=excluded.ftm,
    fta=excluded.fta,
    oreb=excluded.oreb,
    dreb=excluded.dreb,
    pf=excluded.pf,
    source=excluded.source
"""


def default_path():
    """LOCKIN_DB_PATH isolates experiments/tests; otherwise the production file."""
    return Path(os.environ.get("LOCKIN_DB_PATH") or ROOT / "data/lockin.sqlite3")


def split_matchup(matchup):
    text = str(matchup or "")
    if " vs. " in text:
        return 1, text.split(" vs. ", 1)[1].strip() or None
    if " @ " in text:
        return 0, text.split(" @ ", 1)[1].strip() or None
    return 0, None


class GameStore:
    def __init__(self, path=None):
        self.path = Path(path or default_path())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.legacy_mode = False
        self._legacy_refreshes = False
        with self.connect() as db:
            db.executescript(SCHEMA)
            if self._has_table(db, "games") and "payload" in {
                row[1] for row in db.execute("PRAGMA table_info(games)")
            }:
                self.legacy_mode = True
            self._legacy_refreshes = self._has_table(db, "refreshes")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=60)
        db.execute("PRAGMA foreign_keys = ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _has_table(db, name):
        return bool(
            db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
            ).fetchone()
        )

    @staticmethod
    def _number(value):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.0
        return number if math.isfinite(number) else 0.0

    @staticmethod
    def _team_id(db, team_id, abbreviation, name):
        if not abbreviation:
            return None
        name = str(name) if name else str(abbreviation)
        if team_id:
            db.execute(
                "INSERT OR IGNORE INTO dim_teams VALUES (?, ?, ?)",
                (team_id, abbreviation, name),
            )
            if db.execute(
                "SELECT 1 FROM dim_teams WHERE team_id=?", (team_id,)
            ).fetchone():
                if name != abbreviation:
                    db.execute(
                        "UPDATE dim_teams SET abbreviation=?, team_name=? WHERE team_id=?",
                        (abbreviation, name, team_id),
                    )
                return team_id
            # The abbreviation already exists under a surrogate key; reuse it.
        row = db.execute(
            "SELECT team_id FROM dim_teams WHERE abbreviation=?", (abbreviation,)
        ).fetchone()
        if row:
            if name != abbreviation:
                db.execute(
                    "UPDATE dim_teams SET team_name=? WHERE team_id=?",
                    (name, row[0]),
                )
            return row[0]
        db.execute(
            "INSERT INTO dim_teams VALUES (?, ?, ?)",
            (abbreviation, abbreviation, name),
        )
        return abbreviation

    def _record(self, season, row):
        """One uppercase payload dict becomes a normalized fact plus its dims."""
        gid, pid = str(row["GAME_ID"]), str(row["PLAYER_ID"])
        matchup = str(row.get("MATCHUP") or "")
        home, opponent = split_matchup(matchup)
        team_abbreviation = row.get("TEAM_ABBREVIATION")
        if not team_abbreviation and matchup:
            team_abbreviation = (
                matchup.split(" vs. ")[0].split(" @ ")[0].strip() or None
            )
        team_id = row.get("TEAM_ID")
        if team_id in ("", None):
            team_id = None
        elif isinstance(team_id, float):
            team_id = str(int(team_id))
        else:
            team_id = str(team_id)
        return dict(
            season=season,
            game_id=gid,
            player_id=pid,
            player_name=str(row["PLAYER_NAME"]),
            sleeper_id=pid.split(":", 1)[1] if pid.startswith("sleeper:") else None,
            game_date=str(row["GAME_DATE"]),
            team=(team_id, team_abbreviation, row.get("TEAM_NAME")),
            opponent=(None, opponent, None),
            home=home,
            wl=str(row["WL"]) if row.get("WL") is not None else None,
            minutes=self._number(row.get("MIN")),
            stats=[int(self._number(row.get(stat))) for stat in STATS],
            source=row.get("SOURCE") or None,
        )

    def _ingest(self, db, records, reconcile=True):
        from fetch_data import canonical_name

        rows = []
        for record in records:
            db.execute(
                """INSERT INTO dim_players
                (player_id, sleeper_id, canonical_name, display_name)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(player_id) DO UPDATE SET
                    sleeper_id=COALESCE(excluded.sleeper_id, dim_players.sleeper_id),
                    canonical_name=excluded.canonical_name,
                    display_name=excluded.display_name""",
                (
                    record["player_id"],
                    record["sleeper_id"],
                    canonical_name(record["player_name"]),
                    record["player_name"],
                ),
            )
            team_id = self._team_id(db, *record["team"])
            opponent_id = self._team_id(db, *record["opponent"])
            rows.append(
                (
                    record["season"],
                    record["game_id"],
                    record["player_id"],
                    record["game_date"],
                    team_id,
                    opponent_id,
                    record["home"],
                    record["wl"],
                    record["minutes"],
                    *record["stats"],
                    record["source"],
                )
            )
            if reconcile:
                # Providers use different game IDs. Reconcile a fallback row with
                # the NBA row for the same player's date, without double-counting.
                existing = db.execute(
                    """SELECT game_id, source FROM fact_game_logs
                    WHERE season=? AND player_id=? AND game_date=? AND game_id<>?""",
                    (
                        record["season"],
                        record["player_id"],
                        record["game_date"],
                        record["game_id"],
                    ),
                ).fetchall()
                for old_gid, old_source in existing:
                    if "Sleeper / Sportradar" in (old_source, record["source"]):
                        db.execute(
                            """DELETE FROM fact_game_logs
                            WHERE season=? AND game_id=? AND player_id=?""",
                            (record["season"], old_gid, record["player_id"]),
                        )
        db.executemany(UPSERT_SQL, rows)

    def _drain_legacy(self, db, season):
        """Move a season's legacy payload rows into facts before new writes."""
        if not self.legacy_mode:
            return
        rows = db.execute(
            "SELECT payload FROM games WHERE season=?", (season,)
        ).fetchall()
        if not rows:
            return
        self._ingest(
            db,
            (self._record(season, json.loads(payload)) for (payload,) in rows),
            reconcile=False,
        )
        db.execute("DELETE FROM games WHERE season=?", (season,))

    def _refresh_state(self, db, season):
        row = db.execute(
            "SELECT refreshed_on, full_on FROM dim_refreshes WHERE season=?",
            (season,),
        ).fetchone()
        if row is None and self._legacy_refreshes:
            row = db.execute(
                "SELECT refreshed_on, full_on FROM refreshes WHERE season=?",
                (season,),
            ).fetchone()
        return row

    def _latest_date(self, db, season):
        latest = db.execute(
            "SELECT MAX(game_date) FROM fact_game_logs WHERE season=?", (season,)
        ).fetchone()[0]
        if self.legacy_mode:
            legacy = db.execute(
                "SELECT MAX(game_date) FROM games WHERE season=?", (season,)
            ).fetchone()[0]
            latest = max(filter(None, (latest, legacy)), default=None)
        return latest

    def read(self, season):
        from fetch_data import parse_dates

        with self.connect() as db:
            has_facts = db.execute(
                "SELECT 1 FROM fact_game_logs WHERE season=? LIMIT 1", (season,)
            ).fetchone()
            if self.legacy_mode and not has_facts:
                rows = db.execute(
                    "SELECT payload FROM games WHERE season=? ORDER BY game_date, game_id, player_id",
                    (season,),
                ).fetchall()
                if not rows:
                    return pd.DataFrame(
                        columns=["GAME_ID", "PLAYER_ID", "PLAYER_NAME", "GAME_DATE"]
                    )
                return parse_dates(pd.DataFrame([json.loads(row[0]) for row in rows]))
            frame = pd.read_sql_query(READ_SQL, db, params=(season,))
        if frame.empty:
            return pd.DataFrame(
                columns=["GAME_ID", "PLAYER_ID", "PLAYER_NAME", "GAME_DATE"]
            )
        return parse_dates(frame)

    def refresh(self, season, fetch, reference, force=False):
        from fetch_data import parse_dates, normalize_stats_for_scoring

        reference = dt.date.fromisoformat(str(reference))
        # Serialize the read/fetch/write sequence across CLI and dashboard processes.
        with open(str(self.path) + ".lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with self.connect() as db:
                previous = self._refresh_state(db, season)
                latest = self._latest_date(db, season)
            if not force and previous and previous[0] == str(reference):
                return self.read(season)
            full = (
                not previous
                or not latest
                or (reference - dt.date.fromisoformat(previous[1])).days >= 7
            )
            since = (
                None
                if full
                else str(dt.date.fromisoformat(latest) - dt.timedelta(days=7))
            )
            frame = parse_dates(fetch(since))
            records = []
            if not frame.empty:
                if not {"GAME_ID", "PLAYER_ID", "PLAYER_NAME"}.issubset(frame):
                    raise DataUnavailable(
                        "Game history is missing stable game/player identities."
                    )
                normalize_stats_for_scoring(
                    frame
                )  # Validate before committing anything.
                if frame[["GAME_ID", "PLAYER_ID", "PLAYER_NAME"]].isna().any().any():
                    raise DataUnavailable("Game history contains missing identities.")
                frame = frame.copy()
                frame["GAME_DATE"] = frame.GAME_DATE.dt.strftime("%Y-%m-%d")
                for row in json.loads(frame.to_json(orient="records")):
                    gid, pid = str(row["GAME_ID"]), str(row["PLAYER_ID"])
                    if not gid or not pid:
                        raise DataUnavailable("Game history contains empty identities.")
                    # NBA game IDs have ten digits; preserve identity across JSON/parquet types.
                    if gid.isdigit():
                        gid = gid.zfill(10)
                    row.update(GAME_ID=gid, PLAYER_ID=pid)
                    records.append(self._record(season, row))
            elif latest:
                raise DataUnavailable(
                    "NBA returned empty game history; saved games retained."
                )
            with self.connect() as db:
                self._drain_legacy(db, season)
                self._ingest(db, records)
                db.execute(
                    "INSERT OR REPLACE INTO dim_refreshes VALUES (?, ?, ?, ?)",
                    (
                        season,
                        str(reference),
                        str(reference) if full else previous[1],
                        dt.datetime.now(dt.timezone.utc).isoformat(),
                    ),
                )
            return self.read(season)
