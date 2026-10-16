"""Explicit live and historical inputs for one shared analysis pipeline."""

import hashlib
import pandas as pd
from storage import ROOT, read_json
from fetch_data import (
    bulk_player_logs,
    parse_dates,
    normalize_stats_for_scoring,
    _season_for_today,
)
from scoring import add_fantasy_points
from transport import DataUnavailable


class FixtureProvider:
    def __init__(self, directory=None):
        self.directory = directory or ROOT / "data/fixtures/2025-26"
        self.manifest = read_json(self.directory / "manifest.json")
        if not self.manifest:
            raise DataUnavailable(
                "Historical dataset not captured yet. Run capture.py once."
            )
        for name, digest in self.manifest["files"].items():
            path = self.directory / name
            if (
                not path.exists()
                or hashlib.sha256(path.read_bytes()).hexdigest() != digest
            ):
                raise DataUnavailable("Dataset integrity check failed: " + name)
        self.games = parse_dates(pd.read_parquet(self.directory / "games.parquet"))
        self.schedule = parse_dates(
            pd.read_parquet(self.directory / "schedule.parquet")
        )
        self.priors = parse_dates(pd.read_parquet(self.directory / "priors.parquet"))
        self.mode = "replay"

    def remaining(self, pid, observed, reference):
        from fetch_data import get_week_bounds

        _, end = get_week_bounds(reference)
        latest = observed.iloc[-1]
        schedule = self.schedule[self.schedule.TEAM_ID == latest.TEAM_ID]
        if schedule.empty:
            raise DataUnavailable("Team schedule absent from the fixture.")
        ref = pd.Timestamp(reference).normalize()
        return int(
            schedule[
                (
                    (schedule.GAME_DATE >= ref)
                    if getattr(self, "include_today", False)
                    else (schedule.GAME_DATE > ref)
                )
                & (schedule.GAME_DATE <= end)
            ].GAME_ID.nunique()
        )

    def prior(self, pid, weights, reference):
        history = self.priors[
            (self.priors.PLAYER_ID.astype(str) == str(pid))
            & (self.priors.GAME_DATE < pd.Timestamp(reference))
        ]
        return (
            float(add_fantasy_points(history, weights).FP.mean())
            if not history.empty
            else None
        )


class LiveProvider:
    def __init__(self, reference):
        from schedule import SeasonSchedule

        self.mode = "live"
        self.manifest = {
            "season": _season_for_today(reference),
            "source": "NBA Stats API; Sleeper season schedule",
        }
        self.alerts = []
        self.calendar = None
        self.stats_error = None
        self.preseason = False
        self.games = pd.DataFrame(columns=["PLAYER_ID", "PLAYER_NAME", "GAME_DATE"])
        try:
            self.calendar = SeasonSchedule(self.manifest["season"].split("-")[0])
            self.preseason = reference <= self.calendar.start
        except DataUnavailable as exc:
            self.alerts.append(
                {"severity": "error", "message": "Schedule unavailable: " + str(exc)}
            )
        # A drafted fantasy league is already 'in_season' before the NBA tips off.
        # There are no regular-season performances to request or score yet.
        if not self.preseason:
            try:
                self.games = parse_dates(bulk_player_logs(self.manifest["season"]))
            except DataUnavailable as exc:
                self.stats_error = str(exc)
                self.alerts.append(
                    {
                        "severity": "error",
                        "message": "NBA performances unavailable: "
                        + str(exc)
                        + " Rosters and any verified schedule remain available.",
                    }
                )

    def remaining_for_team(self, team, reference):
        if self.calendar is None:
            raise DataUnavailable(
                "Season schedule unavailable. Lock decisions withheld."
            )
        return self.calendar.remaining(team, reference)

    def prior(self, pid, weights, reference):
        history = self.games[
            (self.games.PLAYER_ID.astype(str) == str(pid))
            & (self.games.GAME_DATE < pd.Timestamp(reference) - pd.Timedelta(days=14))
        ]
        if history.empty:
            return None
        return float(
            add_fantasy_points(normalize_stats_for_scoring(history), weights).FP.mean()
        )
