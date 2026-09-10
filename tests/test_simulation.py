import copy
import pandas as pd
import pytest
import simulation
from engine import build_dashboard
from providers import FixtureProvider
from storage import load_cfg, read_json


@pytest.fixture
def practice(tmp_path, monkeypatch):
    provider = FixtureProvider.__new__(FixtureProvider)
    provider.manifest = {
        "week_start": "2025-12-22",
        "week_end": "2025-12-28",
        "default_date": "2025-12-25",
    }
    provider.games = pd.DataFrame(
        [
            dict(
                GAME_DATE=d,
                PLAYER_ID=1,
                PLAYER_NAME="Test Player",
                TEAM_ID=10,
                TEAM_ABBREVIATION="AAA",
                GAME_ID=str(i),
                MIN=30,
                PTS=20 + i,
                REB=5,
                AST=5,
                STL=1,
                BLK=1,
                TOV=2,
                FG3M=1,
                FGM=7,
                FGA=14,
                FTM=3,
                FTA=4,
            )
            for i, d in enumerate(pd.date_range("2025-12-01", "2025-12-28"))
        ]
    )
    provider.schedule = provider.games[["GAME_DATE", "TEAM_ID", "GAME_ID"]].copy()
    provider.priors = provider.games.iloc[:0].copy()
    cfg = load_cfg()
    cfg["teams"] = []
    cfg["test_teams"] = [
        {
            "id": "t",
            "name": "Practice",
            "players": ["Test Player"],
            "starters": ["Test Player"],
        }
    ]
    monkeypatch.setattr(simulation, "PATH", tmp_path / "week.json")
    monkeypatch.setattr(simulation, "FixtureProvider", lambda: provider)
    monkeypatch.setattr(simulation, "load_cfg", lambda: copy.deepcopy(cfg))
    return provider, cfg


def advance(report):
    return simulation.act(
        {"action": "advance", "revision": report["simulation"]["revision"]}
    )


def test_morning_hides_tonight_and_counts_todays_opportunity(practice):
    p, c = practice
    first = simulation.get_report()
    assert first["date"] == "2025-12-22" and first["simulation"]["phase"] == "morning"
    assert first["teams"][0]["results"][0]["status"] == "NO_GAME"
    assert not first["teams"][0]["night_results"]
    assert first["teams"][0]["results"][0]["remaining_games_est"] == 7
    assert first["teams"][0]["results"][0]["fp_mean_recent"] > 0
    evening = advance(first)
    assert evening["teams"][0]["night_results"][0]["date"] == "2025-12-22"
    assert evening["teams"][0]["results"][0]["remaining_games_est"] == 6
    morning = advance(evening)
    row = morning["teams"][0]["results"][0]
    assert row["last_game_date"] == "2025-12-22"
    assert row["remaining_games_est"] == 6
    before = copy.deepcopy(morning["teams"])
    p.games.loc[p.games.GAME_DATE >= "2025-12-23", "PTS"] = 999
    assert simulation.get_report()["teams"] == before


def test_banked_scores_persist_across_nights_and_restart_clears(practice):
    first = simulation.get_report()
    with pytest.raises(ValueError, match="verified completed"):
        simulation.act(
            {
                "action": "bank",
                "team_id": "t",
                "player": "Test Player",
                "revision": first["simulation"]["revision"],
            }
        )
    evening = advance(first)
    banked = simulation.act(
        {
            "action": "bank",
            "team_id": "t",
            "player": "Test Player",
            "revision": evening["simulation"]["revision"],
        }
    )
    score = banked["teams"][0]["banked_total"]
    next_night = advance(advance(banked))
    assert next_night["teams"][0]["banked_total"] == score
    assert next_night["teams"][0]["results"][0]["last_game_fp"] != score
    assert simulation.get_report()["teams"][0]["results"][0]["status"] == "BANKED"
    with pytest.raises(ValueError, match="verified completed"):
        simulation.act(
            {
                "action": "bank",
                "team_id": "t",
                "player": "Test Player",
                "revision": next_night["simulation"]["revision"],
            }
        )
    reset = simulation.act(
        {"action": "reset", "revision": next_night["simulation"]["revision"]}
    )
    assert reset["simulation"]["phase"] == "morning" and reset["date"] == "2025-12-22"
    assert reset["teams"][0]["banked_total"] == 0


def test_stale_actions_rejected_and_edits_isolated(practice):
    _, cfg = practice
    first = simulation.get_report()
    updated = simulation.act(
        {
            "action": "toggle",
            "team_id": "t",
            "player": "Test Player",
            "revision": first["simulation"]["revision"],
        }
    )
    assert updated["teams"][0]["results"][0]["starter"] is False
    assert cfg["test_teams"][0]["starters"] == ["Test Player"]
    with pytest.raises(ValueError, match="another request"):
        advance(first)


def test_end_of_week_cannot_advance_into_future(practice):
    result = simulation.get_report()
    for _ in range(13):
        result = advance(result)
    assert result["simulation"]["finished"] and result["date"] == "2025-12-28"
    with pytest.raises(ValueError, match="week is complete"):
        advance(result)
