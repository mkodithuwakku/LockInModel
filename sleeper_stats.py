"""Final, game-level Sleeper/Sportradar observations when NBA Stats is unavailable.

Sparse counters in this feed omit zeros. Only players with positive playing time
in schedule-confirmed finals are accepted; team points and minutes reconcile the
box score before any rows enter the permanent store. Season totals/projections
and in-progress games can never become observed player games.
"""

import math
import pandas as pd
from fetch_data import canonical_name, player_directory
from game_store import GameStore
from projections import STATS
from storage import ROOT, read_json
from transport import HTTP, DataUnavailable


# Sportradar counters Sleeper may send, plus three-point attempts under `tpa`.
STAT_KEYS = dict(STATS, tpa="FG3A")


def parse_games(payload, games, season, directory):
    if not isinstance(payload, list):
        raise DataUnavailable("Sleeper game stats returned an invalid response.")
    identities = player_directory()
    accepted = []
    reported = set()
    for record in payload:
        if not isinstance(record, dict):
            continue
        game = games.get(str(record.get("game_id")))
        if not game or record.get("category") != "stat":
            continue
        if (
            record.get("company") != "sportradar"
            or str(record.get("season")) != str(season)
            or record.get("season_type") != "regular"
            or record.get("date") != game["date"]
        ):
            continue
        raw = record.get("stats") or {}
        sid = str(record.get("player_id"))
        if sid.startswith("TEAM_") or not raw:
            continue
        try:
            minutes = float(raw["sp"]) / 60
            if not math.isfinite(minutes) or minutes <= 0:
                continue  # DNPs are not zero-point performances.
            observed = {key: float(raw[key]) for key in set(raw) & set(STAT_KEYS)}
            if not all(math.isfinite(v) and v >= 0 for v in observed.values()):
                raise ValueError("Invalid counters")
            metadata = directory.get(sid) or record.get("player") or {}
            name = (
                metadata.get("full_name")
                or " ".join(
                    [metadata.get("first_name", ""), metadata.get("last_name", "")]
                ).strip()
            )
            team = record.get("team")
            if not name or team not in (game["home"], game["away"]):
                raise ValueError("Invalid player/team identity")
            reported |= set(observed)
            accepted.append((game, sid, raw, minutes, name, team))
        except (KeyError, TypeError, ValueError) as exc:
            raise DataUnavailable(
                "Sleeper final box score contains invalid values."
            ) from exc
    if accepted and "pts" not in reported:
        raise DataUnavailable("Sleeper box scores do not report points.")
    # Counters absent from every record are unreported by this feed, not zeros.
    mapping = {key: name for key, name in STAT_KEYS.items() if key in reported}
    rows = {}
    for game, sid, raw, minutes, name, team in accepted:
        stats = {name: float(raw.get(key, 0)) for key, name in mapping.items()}
        opponent = game["away"] if team == game["home"] else game["home"]
        pid = str(identities.get(canonical_name(name), "sleeper:" + sid))
        rows[(game["game_id"], pid)] = dict(
            GAME_ID=game["game_id"],
            PLAYER_ID=pid,
            PLAYER_NAME=name,
            GAME_DATE=game["date"],
            TEAM_ABBREVIATION=team,
            MATCHUP=team + (" vs. " if team == game["home"] else " @ ") + opponent,
            MIN=minutes,
            SOURCE="Sleeper / Sportradar",
            **stats,
        )
    for gid, game in games.items():
        for side in ("home", "away"):
            players = [
                r
                for r in rows.values()
                if r["GAME_ID"] == gid and r["TEAM_ABBREVIATION"] == game[side]
            ]
            expected = game.get(side + "_points")
            if (
                expected is None
                or not players
                or sum(r["PTS"] for r in players) != expected
                or sum(r["MIN"] for r in players) < 239
            ):
                raise DataUnavailable(
                    "Final box scores have not reconciled with the schedule yet; retry the refresh shortly."
                )
    for row in rows.values():
        game = games[row["GAME_ID"]]
        home = row["TEAM_ABBREVIATION"] == game["home"]
        if game["home_points"] != game["away_points"]:
            row["WL"] = (
                "W" if (game["home_points"] > game["away_points"]) == home else "L"
            )
    frame = pd.DataFrame(
        rows.values(),
        columns=None if rows else ["GAME_DATE", "GAME_ID", "PLAYER_ID", "PLAYER_NAME"],
    )
    # This feed has no plus/minus; anything else unreported stays missing too.
    frame.attrs["imputed_stats"] = sorted(
        (set(STAT_KEYS.values()) - set(mapping.values())) | {"PLUS_MINUS"}
    )
    return frame


def completed_logs(calendar, reference):
    season = calendar.season + "-" + str(int(calendar.season) + 1)[-2:]
    directory = read_json(ROOT / "state/sleeper-players.json", {})

    def fetch(since):
        games = {
            g["game_id"]: g
            for g in calendar.games
            if g["status"] in ("complete", "final", "post_game")
            and (since or "") <= g["date"] <= str(reference)
        }
        if not games:
            raise DataUnavailable("No confirmed final games available from Sleeper.")
        weeks = {g.get("week") for g in games.values()}
        if None in weeks:
            raise DataUnavailable("Final schedule is missing its stats week.")
        payload = []
        for week in sorted(weeks):
            data = HTTP.get(
                f"https://api.sleeper.com/stats/nba/{calendar.season}/{week}",
                {"season_type": "regular"},
                ttl=0,
                pace=3,
            )
            if not isinstance(data, list):
                raise DataUnavailable(
                    "Sleeper game stats returned an invalid response."
                )
            payload.extend(data)
        return parse_games(payload, games, calendar.season, directory)

    return GameStore().refresh(season, fetch, reference, force=True)
