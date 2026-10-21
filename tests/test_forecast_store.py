import datetime as dt
from types import SimpleNamespace

import pandas as pd

from forecast_store import ForecastStore, capture_pregame
from test_lineup import logs, projection_cfg


def test_archive_separates_formulas_and_never_backfills(tmp_path):
    store = ForecastStore(tmp_path / "history.sqlite3")
    stamp = dt.datetime(2026, 10, 21, 16, tzinfo=dt.timezone.utc)
    profile = dict(
        projected_fp=20, as_of="2026-10-21", projection_source="current_season"
    )
    store.save_forecasts({"PTS": 1}, "2026-10-21", {"a": profile}, stamp)
    assert store.read_forecasts({"PTS": 1.0, "AST": 0}, "2026-10-21") == {"a": 20}
    assert store.read_forecasts({"PTS": 2}, "2026-10-21") == {}
    store.save_forecasts(
        {"PTS": 1},
        "2026-10-21",
        {"a": dict(profile, projected_fp=999)},
        stamp + dt.timedelta(days=1),
    )
    assert store.read_forecasts({"PTS": 1}, "2026-10-21") == {"a": 20}
    assert store.read("2026-27").empty  # Forecasts never become observations.
    store.save_forecasts(
        {"PTS": 1},
        "2026-10-21",
        {"a": dict(profile, projected_fp=22)},
        stamp + dt.timedelta(hours=1),
    )
    store.save_forecasts({"PTS": 1}, "2026-10-21", {"a": profile}, stamp)
    assert store.read_forecasts({"PTS": 1}, "2026-10-21") == {"a": 22}


def test_capture_only_scheduled_nba_players_and_excludes_same_day_scores():
    saved = []
    store = SimpleNamespace(
        save_forecasts=lambda weights, day, profiles: saved.append(profiles)
    )
    calendar = SimpleNamespace(
        games=[
            dict(date="2026-10-21", status="pre_game", home="BOS", away="NYK"),
            dict(date="2026-10-21", status="in_progress", home="LAL", away="SAS"),
        ]
    )
    directory = {
        "a": dict(full_name="Player A", team="BOS", fantasy_positions=["PG"]),
        "b": dict(full_name="Player B", team="LAL", fantasy_positions=["C"]),
    }
    frame = pd.concat(
        [
            logs([10, 999], ["2026-10-20", "2026-10-21"]).assign(PLAYER_ID="A"),
            logs([100], ["2026-10-20"]).assign(PLAYER_ID="B"),
        ]
    )
    capture_pregame(
        store,
        calendar,
        directory,
        {"player a": "A", "player b": "B"},
        frame,
        None,
        {},
        {"PTS": 1},
        projection_cfg(),
        "2026-10-21",
    )
    assert set(saved[0]) == {"A"} and saved[0]["A"]["projected_fp"] == 10
    calendar.games[0]["status"] = "complete"
    capture_pregame(
        store,
        calendar,
        directory,
        {"player a": "A"},
        frame,
        None,
        {},
        {"PTS": 1},
        projection_cfg(),
        "2026-10-21",
    )
    assert len(saved) == 1
