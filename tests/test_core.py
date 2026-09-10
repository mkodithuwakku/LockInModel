import datetime as dt
import numpy as np
import pandas as pd
import pytest
from fetch_data import normalize_stats_for_scoring, estimate_remaining_games_this_week
from scoring import add_fantasy_points
from decide import per_player_week_decision
from storage import load_cfg
from transport import DataUnavailable
from model import rolling_baseline, rarity_boost


def rows():
    return pd.DataFrame(
        [
            dict(
                GAME_DATE="2025-12-23",
                PTS=50,
                REB=10,
                AST=10,
                STL=2,
                BLK=1,
                TOV=3,
                FG3M=4,
                MIN=35,
                PLAYER_ID=1,
                GAME_ID="0022500001",
            )
        ]
    )


def test_bonus_flags_survive_and_stack():
    cfg = load_cfg()
    raw = rows()
    normalized = normalize_stats_for_scoring(raw)
    assert normalized[["DD", "TD", "PTS40", "PTS50"]].iloc[0].tolist() == [1, 1, 1, 1]
    assert "DD" not in raw
    assert add_fantasy_points(normalized, cfg["weights"]).FP.iloc[0] == 57
    assert normalized.GAME_ID.iloc[0] == "0022500001"


@pytest.mark.parametrize(
    "points,rebounds,assists,expected",
    [
        (39, 9, 9, [0, 0, 0, 0]),
        (40, 10, 9, [1, 0, 1, 0]),
        (49, 10, 10, [1, 1, 1, 0]),
        (50, 10, 10, [1, 1, 1, 1]),
    ],
)
def test_bonus_boundaries(points, rebounds, assists, expected):
    raw = rows()
    raw.loc[0, ["PTS", "REB", "AST"]] = [points, rebounds, assists]
    assert (
        normalize_stats_for_scoring(raw)[["DD", "TD", "PTS40", "PTS50"]]
        .iloc[0]
        .tolist()
        == expected
    )


@pytest.mark.parametrize("bad", [np.nan, "invalid", -1, np.inf])
def test_bad_stats_fail_closed(bad):
    raw = rows()
    raw["REB"] = bad
    with pytest.raises(DataUnavailable):
        normalize_stats_for_scoring(raw)


def test_missing_stats_are_not_assumed_zero():
    with pytest.raises(DataUnavailable):
        normalize_stats_for_scoring(rows().drop(columns="STL"))


def test_unknown_schedule_never_locks():
    result = per_player_week_decision(
        "Test",
        rows(),
        load_cfg()["weights"],
        load_cfg(),
        1,
        dt.date(2025, 12, 24),
        remaining_games=None,
        career_prior=None,
    )
    assert result["status"] == "SCHEDULE_UNAVAILABLE"
    assert result["decision"] is None and result["p_lock"] is None
    assert result["last_game_fp"] == 57


def test_verified_zero_remaining_locks():
    result = per_player_week_decision(
        "Test",
        rows(),
        load_cfg()["weights"],
        load_cfg(),
        1,
        dt.date(2025, 12, 24),
        remaining_games=0,
        career_prior=None,
    )
    assert result["decision"] == "LOCK" and result["p_lock"] == 1


def test_schedule_failure_propagates(monkeypatch):
    def fail(*a, **k):
        raise DataUnavailable("Timeout")

    monkeypatch.setattr("fetch_data.get_player_next_games", fail)
    with pytest.raises(DataUnavailable):
        estimate_remaining_games_this_week(
            1, pd.Timestamp("2025-12-23"), pd.Timestamp("2025-12-28")
        )


def test_empty_schedule_is_unknown(monkeypatch):
    monkeypatch.setattr(
        "fetch_data.get_player_next_games",
        lambda *a, **k: pd.DataFrame(columns=["GAME_DATE"]),
    )
    with pytest.raises(DataUnavailable):
        estimate_remaining_games_this_week(
            1, pd.Timestamp("2025-12-23"), pd.Timestamp("2025-12-28")
        )


def test_future_rows_cannot_change_decision():
    cfg = load_cfg()
    raw = rows()
    later = raw.copy()
    later.GAME_DATE = "2025-12-27"
    later.PTS = 100
    params = dict(
        player_name="Test",
        weights=cfg["weights"],
        cfg=cfg,
        player_id=1,
        reference=dt.date(2025, 12, 24),
        remaining_games=1,
        career_prior=30,
    )
    before = per_player_week_decision(raw_logs=raw, **params)
    after = per_player_week_decision(raw_logs=pd.concat([raw, later]), **params)
    assert before == after


def test_sparse_rarity_and_constant_variance_guard():
    df = pd.DataFrame({"FP": [30] * 5, "STL": [1] * 5})
    b = rolling_baseline(df, cfg=load_cfg())
    assert b["fp_std"] >= 4
    assert (
        rarity_boost(
            pd.Series({"STL": 6}), b["rare_means"], b["rare_stds"], ["STL"], 1.75
        )
        == 0
    )


def test_missing_optional_field_is_rejected_when_it_has_a_weight():
    normalized = normalize_stats_for_scoring(rows())
    with pytest.raises(ValueError, match="FGM"):
        add_fantasy_points(normalized, {"FGM": 1})
