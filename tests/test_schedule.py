import copy
import datetime as dt
import pandas as pd
import pytest

from engine import build_dashboard, roster_dashboard
from providers import LiveProvider
from schedule import SeasonSchedule
from storage import load_cfg
from transport import DataUnavailable


def calendar():
    return SeasonSchedule(
        "2026",
        [
            {
                "game_id": "a",
                "date": "2026-10-20",
                "home": {"team": "PHI"},
                "away": {"team": "BOS"},
                "status": "pre_game",
            },
            {
                "game_id": "b",
                "date": "2026-10-23",
                "home": {"team": "NYK"},
                "away": {"team": "PHI"},
                "status": "pre_game",
            },
            {
                "game_id": "c",
                "date": "2026-10-28",
                "home": {"team": "PHI"},
                "away": {"team": "BOS"},
                "status": "pre_game",
            },
        ],
    )


def cfg():
    config = load_cfg()
    config["teams"] = [
        {
            "id": "sample",
            "name": "Example",
            "source": "sleeper",
            "league_status": "in_season",
            "players": ["Tyrese Maxey"],
            "starters": ["Tyrese Maxey"],
            "player_meta": {
                "tyrese maxey": {
                    "nba_team": "PHI",
                    "positions": ["PG"],
                    "roster_slot": "G",
                    "lineup_order": 0,
                }
            },
        }
    ]
    return config


def install_calendar(monkeypatch):
    monkeypatch.setattr("schedule.SeasonSchedule", lambda *_: calendar())


@pytest.mark.parametrize("day", [15, 20])
def test_drafted_preseason_roster_does_not_request_nonexistent_stats(monkeypatch, day):
    install_calendar(monkeypatch)
    monkeypatch.setattr(
        "providers.bulk_player_logs",
        lambda *_: pytest.fail("No NBA requests before tipoff"),
    )
    reference = dt.date(2026, 10, day)
    provider = LiveProvider(reference)
    report = build_dashboard("live", str(reference), provider=provider, cfg=cfg())
    row = report["teams"][0]["results"][0]
    assert report["alerts"] == []
    assert report["schedule_week"] == ["2026-10-19", "2026-10-25"]
    assert report["observation_cutoff"] == str(reference - dt.timedelta(days=1))
    assert row["status"] == "UPCOMING" and row["decision"] is None
    assert (row["nba_team"], row["roster_slot"]) == ("PHI", "G")
    assert [g["opponent"] for g in row["week_games"]] == ["BOS", "NYK"]
    assert not any(g["fp"] is not None for g in row["week_games"])


def test_stats_failure_keeps_verified_schedule_and_other_leagues(monkeypatch, tmp_path):
    monkeypatch.setattr("game_store.ROOT", tmp_path)
    install_calendar(monkeypatch)

    def fail(*_):
        raise DataUnavailable("stats.nba.com request failed; cooldown active.")

    monkeypatch.setattr("providers.bulk_player_logs", fail)
    config = cfg()
    config["teams"].append(
        dict(config["teams"][0], id="draft", league_status="pre_draft")
    )
    report = build_dashboard(
        "live", "2026-10-22", provider=LiveProvider(dt.date(2026, 10, 22)), cfg=config
    )
    assert len(report["teams"]) == 2
    row = report["teams"][0]["results"][0]
    assert row["status"] == "DATA_UNAVAILABLE" and row["decision"] is None
    assert row["schedule_state"] == "verified" and len(row["week_games"]) == 2
    assert row["nba_team"] == "PHI"
    assert report["teams"][1]["results"][0]["status"] == "PRE_DRAFT"
    assert (
        len(report["alerts"]) == 1
        and "performances unavailable" in report["alerts"][0]["message"]
    )


def test_failed_refresh_never_recommends_pickups_from_saved_history(
    monkeypatch, tmp_path
):
    install_calendar(monkeypatch)
    monkeypatch.setattr("game_store.ROOT", tmp_path)
    history = pd.DataFrame(
        [
            dict(
                PLAYER_ID=1630178,
                PLAYER_NAME="Tyrese Maxey",
                GAME_DATE=pd.Timestamp("2026-10-20"),
            )
        ]
    )
    monkeypatch.setattr("game_store.GameStore.read", lambda *_: history)

    def fail(*_):
        raise DataUnavailable("Offline")

    monkeypatch.setattr("providers.bulk_player_logs", fail)
    monkeypatch.setattr(
        "engine.find_pickups",
        lambda *_: pytest.fail("Saved stale history cannot authorize pickups"),
    )
    provider = LiveProvider(dt.date(2026, 10, 22))
    assert not provider.games.empty
    result = build_dashboard("live", "2026-10-22", provider=provider, cfg=cfg())
    assert result["teams"][0]["pickups"] == []
    assert result["teams"][0]["results"][0]["decision"] is None


def test_schedule_failure_preserves_boxscores_but_cannot_lock(monkeypatch):
    def fail(*_):
        raise DataUnavailable("Schedule offline")

    monkeypatch.setattr("schedule.SeasonSchedule", fail)
    history = pd.DataFrame(
        [
            dict(
                PLAYER_ID=1630178,
                PLAYER_NAME="Tyrese Maxey",
                GAME_DATE="2026-10-20",
                TEAM_ABBREVIATION="PHI",
                PTS=50,
                REB=10,
                AST=10,
                STL=2,
                BLK=1,
                TOV=3,
                FG3M=4,
                MIN=35,
            )
        ]
    )
    monkeypatch.setattr("providers.bulk_player_logs", lambda *_: history)
    report = build_dashboard(
        "live", "2026-10-22", provider=LiveProvider(dt.date(2026, 10, 22)), cfg=cfg()
    )
    row = report["teams"][0]["results"][0]
    assert row["status"] == "SCHEDULE_UNAVAILABLE" and row["decision"] is None
    assert row["last_game_fp"] is not None and row["history"]
    assert row["schedule_state"] == "unavailable"


def test_fallback_rosters_keep_team_positions_and_injury_metadata():
    config = cfg()
    config["teams"][0]["player_meta"]["tyrese maxey"]["injury_status"] = "DTD"
    row = roster_dashboard(config)["teams"][0]["results"][0]
    assert row["nba_team"] == "PHI" and row["positions"] == ["PG"]
    assert row["roster_slot"] == "G" and row["injury_status"] == "DTD"


def test_verified_schedule_counts_today_and_distinguishes_unknown_team():
    c = calendar()
    assert c.remaining("PHI", dt.date(2026, 10, 23)) == 1
    assert c.remaining("PHI", dt.date(2026, 10, 24)) == 0
    with pytest.raises(DataUnavailable):
        c.remaining("UNKNOWN", dt.date(2026, 10, 24))
    c.games[1]["status"] = "postponed"
    with pytest.raises(DataUnavailable):
        c.remaining("PHI", dt.date(2026, 10, 23))


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        [{"game_id": "a"}],
        [
            {
                "game_id": "a",
                "date": "2025-10-20",
                "home": {"team": "PHI"},
                "away": {"team": "BOS"},
                "status": "pre_game",
            }
        ],
    ],
)
def test_empty_malformed_or_wrong_season_schedule_is_not_zero(payload):
    with pytest.raises(DataUnavailable):
        SeasonSchedule("2026", payload)
