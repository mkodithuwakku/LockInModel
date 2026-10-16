"""One cached, read-only Sleeper season schedule; no per-player requests."""

import datetime as dt
from fetch_data import get_week_bounds
from transport import HTTP, DataUnavailable


class SeasonSchedule:
    def __init__(self, season, payload=None):
        self.season = str(season)
        data = (
            payload
            if payload is not None
            else HTTP.get(
                f"https://api.sleeper.app/schedule/nba/regular/{self.season}",
                ttl=21600,
                pace=3,
            )
        )
        if not isinstance(data, list) or not data:
            raise DataUnavailable("Sleeper season schedule is empty or unavailable.")
        self.games = []
        seen = set()
        try:
            for item in data:
                date = dt.date.fromisoformat(item["date"][:10])
                if date < dt.date(int(season), 9, 1) or date > dt.date(
                    int(season) + 1, 8, 31
                ):
                    raise ValueError("Wrong schedule season")
                home, away = item["home"]["team"], item["away"]["team"]
                if not home or not away or home == away or not item["game_id"]:
                    raise ValueError("Invalid game identity")
                if item["game_id"] in seen:
                    raise ValueError("Duplicate game")
                seen.add(item["game_id"])
                self.games.append(
                    {
                        "date": str(date),
                        "home": home,
                        "away": away,
                        "game_id": str(item["game_id"]),
                        "status": str(item["status"]),
                    }
                )
        except (KeyError, ValueError, TypeError, IndexError) as exc:
            raise DataUnavailable(
                "Sleeper season schedule has invalid game records."
            ) from exc
        self.games.sort(key=lambda g: (g["date"], g["game_id"]))
        self.start = dt.date.fromisoformat(self.games[0]["date"])
        self.end = dt.date.fromisoformat(self.games[-1]["date"])
        self.teams = {g[side] for g in self.games for side in ("home", "away")}

    def display_week(self, reference):
        # Before tipoff, show the opening week without moving the analysis cutoff.
        return [str(d.date()) for d in get_week_bounds(max(reference, self.start))]

    def for_team(self, team, week):
        if team not in self.teams:
            raise DataUnavailable("NBA team is not present in the season schedule.")
        return [
            {
                "date": g["date"],
                "opponent": g["away"] if g["home"] == team else g["home"],
                "home": g["home"] == team,
                "status": g["status"],
                "game_id": g["game_id"],
            }
            for g in self.games
            if week[0] <= g["date"] <= week[1] and team in (g["home"], g["away"])
        ]

    def remaining(self, team, reference):
        week = [str(d.date()) for d in get_week_bounds(reference)]
        if reference > self.end:
            raise DataUnavailable(
                "Reference date is beyond the published season schedule."
            )
        games = self.for_team(team, week)
        # Postponed/cancelled entries cannot establish a confident count or zero.
        if any(
            g["status"]
            not in ("pre_game", "in_progress", "complete", "final", "post_game")
            for g in games
        ):
            raise DataUnavailable(
                "Team schedule includes an unconfirmed or postponed game."
            )
        return sum(
            g["date"] >= str(reference)
            and g["status"] not in ("complete", "final", "post_game")
            for g in games
        )
