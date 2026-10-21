import datetime as dt
import pytest

from sleeper_stats import parse_games
from transport import DataUnavailable


def fixture():
    games = {
        "game": dict(
            game_id="game",
            date="2026-10-20",
            home="BOS",
            away="DET",
            home_points=10,
            away_points=12,
        )
    }
    rows = [
        dict(
            game_id="game",
            date="2026-10-20",
            category="stat",
            company="sportradar",
            season="2026",
            season_type="regular",
            player_id=str(i),
            player={"first_name": "Example", "last_name": str(i)},
            team=team,
            stats={"pts": pts, "sp": 240 * 60},
        )
        for i, (team, pts) in enumerate([("BOS", 10), ("DET", 12)])
    ]
    return rows, games


def test_sparse_final_stats_are_observations_not_totals_or_forecasts():
    rows, games = fixture()
    rows += [
        dict(rows[0], game_id="season"),
        dict(rows[0], category="proj"),
        dict(rows[0], player_id="dnp", stats={}),
    ]
    frame = parse_games(rows, games, "2026", {})
    assert len(frame) == 2 and frame.PTS.tolist() == [10, 12]
    assert frame.WL.tolist() == ["L", "W"]
    assert frame.FG3M.tolist() == [0, 0]
    assert frame.FG3A.tolist() == [0, 0]
    assert frame.SOURCE.unique().tolist() == ["Sleeper / Sportradar"]
    assert frame.PLAYER_ID.tolist() == ["sleeper:0", "sleeper:1"]


@pytest.mark.parametrize(
    "change",
    ["missing", "wrong_date", "wrong_season", "negative", "nan", "partial_minutes"],
)
def test_incomplete_or_invalid_final_is_rejected(change):
    rows, games = fixture()
    if change == "missing":
        rows.pop()
    elif change == "wrong_date":
        rows[0]["date"] = "2026-10-21"
    elif change == "wrong_season":
        rows[0]["season"] = "2025"
    elif change == "partial_minutes":
        rows[0]["stats"]["sp"] = 300
    else:
        rows[0]["stats"]["reb"] = -1 if change == "negative" else float("nan")
    with pytest.raises(DataUnavailable):
        parse_games(rows, games, "2026", {})


def test_opening_night_final_uses_fallback_and_reaches_roster(monkeypatch):
    from providers import LiveProvider
    from engine import build_dashboard
    from test_schedule import calendar, cfg

    c = calendar()
    c.games[0]["status"] = "complete"
    monkeypatch.setattr("schedule.SeasonSchedule", lambda *_: c)

    def fail(*_):
        raise DataUnavailable("NBA offline")

    monkeypatch.setattr("providers.bulk_player_logs", fail)
    from test_game_store import games

    frame = games().assign(
        PLAYER_ID="1630178", PLAYER_NAME="Tyrese Maxey", TEAM_ABBREVIATION="PHI", MIN=30
    )
    monkeypatch.setattr("sleeper_stats.completed_logs", lambda *_: frame)
    p = LiveProvider(dt.date(2026, 10, 20))
    assert not p.preseason and p.stats_error is None and not p.alerts
    r = build_dashboard("live", "2026-10-20", p, cfg())
    row = r["teams"][0]["results"][0]
    assert row["last_game_date"] == "2026-10-20" and row["last_game_fp"] is not None
    assert row["week_games"][0]["fp"] == row["last_game_fp"]
    # An identical box score must not leak into the view before its final status.
    c.games[0]["status"] = "in_progress"
    row = build_dashboard("live", "2026-10-20", p, cfg())["teams"][0]["results"][0]
    assert row.get("last_game_fp") is None and row["week_games"][0]["fp"] is None


def test_three_point_attempts_survive_fallback_ingestion():
    rows, games = fixture()
    rows[0]["stats"].update(tpa=7, tpm=2)
    frame = parse_games(rows, games, "2026", {})
    assert frame.iloc[0].FG3A == 7 and frame.iloc[0].FG3M == 2
