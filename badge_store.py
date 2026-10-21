"""Season badge ledger in the existing local DB; corrected nights replace awards."""

import datetime as dt
import hashlib
import json
import sqlite3
from collections import Counter

import pandas as pd

from badge_awards import EXTRA_KEYS, fantasy_awards, raw_awards
from daily_badges import (
    CATEGORIES,
    FANTASY_CATEGORIES,
    previous_night_badges,
    fantasy_night_badges,
)
from forecast_store import ForecastStore, formula_key

RULES_VERSION = 1
BADGE_KEYS = tuple(CATEGORIES) + tuple(FANTASY_CATEGORIES) + tuple(EXTRA_KEYS)
NEGATIVE_KEYS = frozenset(
    {
        "bricks",
        "sandwich",
        "heartbreak",
        "careless",
        "underachiever",
        "inefficient",
        "cold_streak",
        "win_low",
    }
)
MILESTONE_KEYS = frozenset(
    {k for k in BADGE_KEYS if k.startswith("milestone_")} | {"coffee", "magician"}
)


def season_bounds(reference, season=None):
    ref = dt.date.fromisoformat(str(reference))
    year = int(str(season)[:4]) if season else ref.year - (ref.month < 10)
    start = dt.date(year, 10, 1)
    end = min(ref - dt.timedelta(days=1), dt.date(year + 1, 9, 30))
    return str(year), start, end


def empty_summary(reference, season=None, status="empty"):
    year, _, end = season_bounds(reference, season)
    return dict(
        season=year,
        as_of=str(end),
        status=status,
        first_date=None,
        last_date=None,
        tracked_days=0,
        player_games=0,
        forecast_player_games=0,
        total_awards=0,
        negative_keys=sorted(NEGATIVE_KEYS),
        milestone_keys=sorted(MILESTONE_KEYS),
        players=[],
    )


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


class BadgeStore(ForecastStore):
    def __init__(self, path=None):
        super().__init__(path)
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS badge_days (
                    season TEXT NOT NULL, formula_key TEXT NOT NULL, game_date TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, player_games INTEGER NOT NULL,
                    forecast_player_games INTEGER NOT NULL,
                    PRIMARY KEY (season, formula_key, game_date)
                );
                CREATE TABLE IF NOT EXISTS badge_awards (
                    season TEXT NOT NULL, formula_key TEXT NOT NULL, game_date TEXT NOT NULL,
                    player_id TEXT NOT NULL, badge_key TEXT NOT NULL,
                    player_name TEXT NOT NULL, nba_team TEXT NOT NULL,
                    PRIMARY KEY (season, formula_key, game_date, player_id, badge_key)
                );
            """
            )

    @classmethod
    def saved_summary(cls, reference, weights, season=None, path=None):
        """Read completed seasons without creating tables or touching live inputs."""
        from storage import ROOT
        from pathlib import Path

        path = Path(path or ROOT / "data/lockin.sqlite3").resolve()
        if not path.exists():
            return empty_summary(reference, season)
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
            tables = {
                r[0]
                for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        if not {"badge_days", "badge_awards"}.issubset(tables):
            return empty_summary(reference, season)
        store = cls.__new__(cls)
        store.path = path
        return store.summary(reference, weights, season)

    def sync(
        self, games, reference, weights, calendar=None, birthdays=None, season=None
    ):
        year, start, end = season_bounds(reference, season)
        if (
            games is None
            or games.empty
            or not {"PLAYER_ID", "GAME_DATE"}.issubset(games)
        ):
            return self.summary(reference, weights, year)
        frame = games.copy()
        frame["GAME_DATE"] = pd.to_datetime(frame.GAME_DATE, errors="coerce")
        frame = frame[frame.GAME_DATE.dt.date.between(start, end)].dropna(
            subset=["PLAYER_ID"]
        )
        frame["PLAYER_ID"] = frame.PLAYER_ID.astype(str)
        keys = (
            ["PLAYER_ID", "GAME_ID"]
            if "GAME_ID" in frame
            else ["PLAYER_ID", "GAME_DATE"]
        )
        frame = (
            frame.drop_duplicates(keys, keep="last")
            .sort_values(["GAME_DATE"] + keys)
            .reset_index(drop=True)
        )
        if frame.empty:
            return self.summary(reference, weights, year)
        formula = formula_key(weights)
        with self.connect() as db:
            cached = dict(
                db.execute(
                    "SELECT game_date, fingerprint FROM badge_days WHERE season=? AND formula_key=?",
                    (year, formula),
                )
            )
            snapshots = db.execute(
                "SELECT game_date, player_id, projected_fp FROM forecast_snapshots WHERE formula_key=? AND game_date BETWEEN ? AND ?",
                (formula, str(start), str(end)),
            ).fetchall()
        forecasts = {}
        for day, pid, fp in snapshots:
            forecasts.setdefault(day, {})[pid] = fp
        calendar_days = {}
        for game in calendar or []:
            calendar_days.setdefault(game["date"], []).append(game)
        # Prefix hashes make earlier corrections invalidate later streak calculations.
        prefix_hash = digest(
            {
                "rules": RULES_VERSION,
                "birthdays": birthdays or {},
                "imputed": sorted(frame.attrs.get("imputed_stats", [])),
            }
        )
        replacements = []
        for timestamp, night in frame.groupby("GAME_DATE", sort=True):
            day = str(timestamp.date())
            records = json.loads(
                night.reindex(sorted(night.columns), axis=1).to_json(
                    orient="records", date_format="iso"
                )
            )
            prefix_hash = digest([prefix_hash, records])
            context = sorted(
                calendar_days.get(day, []), key=lambda g: str(g.get("game_id", ""))
            )
            saved = forecasts.get(day, {})
            fingerprint = digest([prefix_hash, context, saved])
            if cached.get(day) == fingerprint:
                continue
            next_day = timestamp.date() + dt.timedelta(days=1)
            prefix = frame.loc[: night.index.max()]
            groups = (
                previous_night_badges(night, next_day),
                raw_awards(night, next_day),
                fantasy_night_badges(night, next_day, weights, saved),
                fantasy_awards(prefix, next_day, weights, context, birthdays),
            )
            identities = {
                str(r.PLAYER_ID): (
                    str(r.get("PLAYER_NAME") or r.PLAYER_ID),
                    str(r.get("TEAM_ABBREVIATION") or ""),
                )
                for _, r in night.iterrows()
            }
            earned = {
                (pid, b["key"])
                for group in groups
                for pid, badges in group.items()
                for b in badges
                if b["key"] in BADGE_KEYS
            }
            rows = [
                (year, formula, day, pid, key, *identities[pid])
                for pid, key in sorted(earned)
            ]
            coverage = len(set(night.PLAYER_ID) & set(saved))
            replacements.append(
                ((year, formula, day, fingerprint, len(night), coverage), rows)
            )
        # One transaction: readers never see half of a corrected season update.
        with self.connect() as db:
            for meta, rows in replacements:
                db.execute(
                    "DELETE FROM badge_awards WHERE season=? AND formula_key=? AND game_date=?",
                    meta[:3],
                )
                db.executemany(
                    "INSERT INTO badge_awards VALUES (?, ?, ?, ?, ?, ?, ?)", rows
                )
                db.execute(
                    "INSERT OR REPLACE INTO badge_days VALUES (?, ?, ?, ?, ?, ?)", meta
                )
        return self.summary(reference, weights, year)

    def summary(self, reference, weights, season=None, stale=False):
        result = empty_summary(reference, season)
        year, start, end = season_bounds(reference, season)
        formula = formula_key(weights)
        with self.connect() as db:
            days = db.execute(
                "SELECT game_date, player_games, forecast_player_games FROM badge_days WHERE season=? AND formula_key=? AND game_date BETWEEN ? AND ? ORDER BY game_date",
                (year, formula, str(start), str(end)),
            ).fetchall()
            rows = db.execute(
                "SELECT game_date, player_id, badge_key, player_name, nba_team FROM badge_awards WHERE season=? AND formula_key=? AND game_date BETWEEN ? AND ? ORDER BY game_date, player_id, badge_key",
                (year, formula, str(start), str(end)),
            ).fetchall()
        players = {}
        for day, pid, key, name, team in rows:
            player = players.setdefault(
                pid,
                dict(
                    player_id=pid,
                    player=name,
                    nba_team=team,
                    counts=Counter(),
                    last_award=day,
                ),
            )
            player.update(player=name, nba_team=team, last_award=day)
            player["counts"][key] += 1
        for player in players.values():
            counts = player["counts"]
            player.update(
                total=sum(counts.values()),
                negative=sum(counts[k] for k in NEGATIVE_KEYS),
                milestones=sum(counts[k] for k in MILESTONE_KEYS),
                variety=len(counts),
            )
            player["counts"] = dict(counts)
        result.update(
            status="saved" if stale and days else "ready" if days else "empty",
            players=sorted(
                players.values(),
                key=lambda p: (-p["total"], p["player"], p["player_id"]),
            ),
            total_awards=len(rows),
            tracked_days=len(days),
            player_games=sum(d[1] for d in days),
            forecast_player_games=sum(d[2] for d in days),
            first_date=days[0][0] if days else None,
            last_date=days[-1][0] if days else None,
        )
        return result
