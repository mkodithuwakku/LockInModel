"""Pregame forecasts in the existing local SQLite database, separate from results."""

import datetime as dt
import hashlib
import json
import math
from zoneinfo import ZoneInfo

from game_store import GameStore
from fetch_data import canonical_name
from lineup import project_players
from projections import forecast_profile


def formula_key(weights):
    rules = {k: float(v) for k, v in weights.items() if v}
    return hashlib.sha256(json.dumps(rules, sort_keys=True).encode()).hexdigest()


class ForecastStore(GameStore):
    def __init__(self, path=None):
        super().__init__(path)
        with self.connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS forecast_snapshots (
                formula_key TEXT NOT NULL, game_date TEXT NOT NULL,
                player_id TEXT NOT NULL, projected_fp REAL NOT NULL,
                captured_at TEXT NOT NULL, source TEXT NOT NULL,
                PRIMARY KEY (formula_key, game_date, player_id)
            )"""
            )

    def read_forecasts(self, weights, day):
        with self.connect() as db:
            rows = db.execute(
                "SELECT player_id, projected_fp FROM forecast_snapshots WHERE formula_key=? AND game_date=?",
                (formula_key(weights), str(day)),
            ).fetchall()
        return dict(rows)

    def save_forecasts(self, weights, day, profiles, captured_at=None):
        captured = captured_at or dt.datetime.now(dt.timezone.utc)
        # Only the actual refresh day may create/update pregame snapshots. Replay
        # and later refreshes cannot manufacture a historical forecast.
        if captured.astimezone(ZoneInfo("America/Edmonton")).date().isoformat() != str(
            day
        ):
            return
        rows = []
        for pid, profile in profiles.items():
            value = profile.get("projected_fp")
            if (
                isinstance(value, (int, float))
                and math.isfinite(value)
                and profile.get("as_of") == str(day)
            ):
                rows.append(
                    (
                        formula_key(weights),
                        str(day),
                        str(pid),
                        value,
                        captured.isoformat(),
                        profile["projection_source"],
                    )
                )
        with self.connect() as db:
            db.executemany(
                """INSERT INTO forecast_snapshots VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(formula_key, game_date, player_id) DO UPDATE SET
                projected_fp=excluded.projected_fp, captured_at=excluded.captured_at,
                source=excluded.source WHERE excluded.captured_at > forecast_snapshots.captured_at""",
                rows,
            )


def capture_pregame(
    store,
    calendar,
    directory,
    identity,
    observed,
    fallback,
    forecasts,
    weights,
    cfg,
    reference,
):
    """Save today's NBA pool, only for teams whose games have not started."""
    if calendar is None:
        return
    teams = {
        g[side]
        for g in calendar.games
        if g["date"] == str(reference) and g["status"] in {"pre_game", "scheduled"}
        for side in ("home", "away")
    }
    players = {}
    for sid, player in directory.items():
        if player.get("team") not in teams or not player.get("fantasy_positions"):
            continue
        name = (
            player.get("full_name")
            or (
                player.get("first_name", "") + " " + player.get("last_name", "")
            ).strip()
        )
        pid = str(identity.get(canonical_name(name), "sleeper:" + str(sid)))
        players[pid] = str(sid)
    if not players:
        return
    profiles = project_players(
        observed[observed.PLAYER_ID.astype(str).isin(players)],
        (
            fallback[fallback.PLAYER_ID.astype(str).isin(players)]
            if fallback is not None and not fallback.empty
            else None
        ),
        weights,
        cfg,
        reference,
    )
    for pid, sid in players.items():
        if profiles.get(pid, {}).get("projection_source") in {
            "current_season",
            "blended_seasons",
        }:
            continue
        if sid in forecasts:
            try:
                profiles[pid] = forecast_profile(forecasts[sid], weights, reference)
            except (ValueError, KeyError):
                continue
    store.save_forecasts(weights, reference, profiles)
