import copy
import math

import pandas as pd
import pytest

from projections import parse_forecasts, forecast_profile, poisson_tail
from transport import DataUnavailable


def record():
    return {
        "category": "proj",
        "company": "rotowire",
        "season": "2026",
        "season_type": "regular",
        "game_id": "season",
        "updated_at": 1792540240342,
        "player_id": "rookie",
        "stats": {
            "gp": 1,
            "pts": 20,
            "reb": 6,
            "dreb": 4,
            "ast": 5,
            "stl": 1,
            "blk": 0.5,
            "to": 2,
            "tpm": 2,
            "sp": 1800,
            "dd": 0.2,
            "ftm": 4,
            "fta": 5,
            "fgm": 7,
            "fga": 15,
        },
    }


def test_per_game_and_season_totals_are_equivalent():
    raw = record()
    a = parse_forecasts([raw], "2026")["rookie"]
    assert a["stats"]["MIN"] == 30 and a["stats"]["OREB"] == 2
    total = copy.deepcopy(raw)
    total["stats"] = {k: v * 70 for k, v in raw["stats"].items()}
    assert parse_forecasts([total], "2026")["rookie"] == a
    result = forecast_profile(
        a, {"PTS": 1, "OREB": 2, "DREB": 1, "DD": 10, "PF": -1}, "2026-10-20"
    )
    assert (
        result["projected_fp"] == 30
    )  # 20 + 4 + 4 + 2 expected bonus; absent fouls omitted.
    assert result["projection_source"] == "sleeper_rotowire"
    assert result["projected_stats"]["AST"] == 5
    assert result["last_played"] is None and result["sample_size"] is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("season", "2025"),
        ("season_type", "post"),
        ("category", "stat"),
        ("company", "unknown"),
    ],
)
def test_wrong_forecast_scope_rejected(field, value):
    raw = record()
    raw[field] = value
    with pytest.raises(DataUnavailable):
        parse_forecasts([raw], "2026")


@pytest.mark.parametrize(
    "key,value", [("gp", 0), ("pts", float("nan")), ("sp", -1), ("dd", 2)]
)
def test_invalid_or_missing_values_are_not_zero_projections(key, value):
    raw = record()
    raw["stats"][key] = value
    with pytest.raises(DataUnavailable):
        parse_forecasts([raw], "2026")
    raw = record()
    del raw["stats"]["ast"]
    with pytest.raises(DataUnavailable):
        parse_forecasts([raw], "2026")


def test_milestones_use_probability_not_a_threshold_on_the_average():
    forecast = parse_forecasts([record()], "2026")["rookie"]
    p = forecast_profile(forecast, {"PTS40": 1000}, "2026-10-20")
    assert p["projected_fp"] == round(poisson_tail(20, 40) * 1000, 2) > 0
    assert any("Poisson" in note for note in p["scoring_notes"])
    assert poisson_tail(0, 15) == 0
    assert poisson_tail(10, 1) == pytest.approx(1 - math.exp(-10))
    q = forecast_profile(forecast, {"DD": 10, "TD": 20}, "2026-10-20")
    assert q["projected_fp"] >= 2


def test_projection_is_independent_of_start_eligibility():
    from lineup import recommend_lineup

    p = forecast_profile(
        parse_forecasts([record()], "2026")["rookie"], {"PTS": 1}, "2026-10-20"
    )
    rows = [
        {
            "player": "Rookie",
            "player_id": None,
            "positions": ["PF"],
            "projection": p,
            "roster_slot": "BN",
            "schedule_state": "verified",
            "week_games": [{"date": "2026-10-20", "status": "pre_game"}],
        }
    ]
    a = recommend_lineup({"roster_positions": ["F"]}, rows, {}, "2026-10-20")
    assert a["slots"][0]["player"] == "Rookie" and a["total_projected_fp"] == 20
    rows[0]["injury_status"] = "Out"
    b = recommend_lineup({"roster_positions": ["F"]}, rows, {}, "2026-10-20")
    assert b["filled_slots"] == 0 and b["bench"][0]["projected_fp"] == 20
    assert rows[0]["projection"]["projected_fp"] == 20


def test_export_projection_nested_fields_are_allowlisted():
    from pages import public_projection

    p = forecast_profile(
        parse_forecasts([record()], "2026")["rookie"], {"PTS": 1}, "2026-10-20"
    )
    p["secret"] = "private"
    p["projected_stats"]["secret"] = "private"
    result = public_projection(p)
    assert "secret" not in result and "secret" not in result["projected_stats"]
    assert result["projected_stats"]["PTS"] == 20


def test_rookie_and_bench_projection_integration_without_nba_id(monkeypatch):
    from test_schedule import calendar, cfg
    from engine import build_dashboard
    from types import SimpleNamespace

    config = cfg()
    t = config["teams"][0]
    t.update(
        players=["New Rookie"],
        starters=[],
        roster_positions=["F"],
        ignored_scoring={"tf": -1},
    )
    t["player_meta"] = {
        "new rookie": {
            "positions": ["PF"],
            "nba_team": "PHI",
            "sleeper_id": "rookie",
            "roster_slot": "BN",
        }
    }
    monkeypatch.setattr(
        "projections.fetch_forecasts", lambda *_: parse_forecasts([record()], "2026")
    )
    provider = SimpleNamespace(
        games=pd.DataFrame(columns=["PLAYER_ID", "PLAYER_NAME", "GAME_DATE"]),
        calendar=calendar(),
        preseason=True,
        manifest={"season": "2026-27"},
    )
    report = build_dashboard("live", "2026-10-20", provider, config)
    row = report["teams"][0]["results"][0]
    assert row["projection"]["projected_fp"] is not None
    assert row["projection"]["projected_stats"]["MIN"] == 30
    assert not row["starter"] and row["player_id"] is None
    assert report["teams"][0]["recommended_lineup"]["filled_slots"] == 1
    assert report["alerts"] == [] and report["teams"][0]["scoring_notes"]


def test_explicit_missing_projection_does_not_reuse_stale_history():
    from lineup import recommend_lineup

    rows = [
        {
            "player": "A",
            "player_id": "A",
            "positions": ["PG"],
            "projection": None,
            "schedule_state": "verified",
            "week_games": [{"date": "2026-10-20", "status": "pre_game"}],
        }
    ]
    result = recommend_lineup(
        {"roster_positions": ["PG"]}, rows, {"A": {"projected_fp": 50}}, "2026-10-20"
    )
    assert result["filled_slots"] == 0 and result["status"] == "partial"
