"""Permanent local player-game history, shared by every live league.

Refreshes append new games and upsert corrections by season/game/player. A rolling
seven-day overlap catches recent corrections; weekly full reads reconcile older
ones. Failed requests never advance freshness or remove existing observations.
"""

from contextlib import contextmanager
import datetime as dt
import fcntl
import json
from pathlib import Path
import sqlite3

import pandas as pd
from storage import ROOT
from transport import DataUnavailable


class GameStore:
    def __init__(self, path=None):
        self.path = Path(path or ROOT / "data/lockin.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS games (
                    season TEXT NOT NULL,
                    game_id TEXT NOT NULL,
                    player_id TEXT NOT NULL,
                    game_date TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (season, game_id, player_id)
                );
                CREATE TABLE IF NOT EXISTS refreshes (
                    season TEXT PRIMARY KEY,
                    refreshed_on TEXT NOT NULL,
                    full_on TEXT NOT NULL,
                    fetched_at TEXT NOT NULL
                );
            """
            )

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=60)
        try:
            with db:
                yield db
        finally:
            db.close()

    def read(self, season):
        from fetch_data import parse_dates

        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM games WHERE season=? ORDER BY game_date, game_id, player_id",
                (season,),
            ).fetchall()
        if not rows:
            return pd.DataFrame(
                columns=["GAME_ID", "PLAYER_ID", "PLAYER_NAME", "GAME_DATE"]
            )
        return parse_dates(pd.DataFrame([json.loads(row[0]) for row in rows]))

    def refresh(self, season, fetch, reference):
        from fetch_data import parse_dates, normalize_stats_for_scoring

        reference = dt.date.fromisoformat(str(reference))
        # Serialize the read/fetch/write sequence across CLI and dashboard processes.
        with open(str(self.path) + ".lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with self.connect() as db:
                previous = db.execute(
                    "SELECT refreshed_on, full_on FROM refreshes WHERE season=?",
                    (season,),
                ).fetchone()
                latest = db.execute(
                    "SELECT MAX(game_date) FROM games WHERE season=?", (season,)
                ).fetchone()[0]
            if previous and previous[0] == str(reference):
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
                    records.append(
                        (
                            season,
                            gid,
                            pid,
                            row["GAME_DATE"],
                            json.dumps(row, allow_nan=False),
                        )
                    )
            elif latest:
                raise DataUnavailable(
                    "NBA returned empty game history; saved games retained."
                )
            with self.connect() as db:
                db.executemany(
                    """INSERT INTO games VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(season, game_id, player_id) DO UPDATE SET
                    game_date=excluded.game_date, payload=excluded.payload""",
                    records,
                )
                db.execute(
                    "INSERT OR REPLACE INTO refreshes VALUES (?, ?, ?, ?)",
                    (
                        season,
                        str(reference),
                        str(reference) if full else previous[1],
                        dt.datetime.now(dt.timezone.utc).isoformat(),
                    ),
                )
            return self.read(season)
