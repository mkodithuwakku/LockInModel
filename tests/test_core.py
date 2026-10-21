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


def test_saved_foul_rules_migrate_without_ignoring_unknown_gaps():
    from storage import validate_config

    cfg = load_cfg()
    cfg["teams"] = [
        {
            "id": "test",
            "name": "Test",
            "players": [],
            "starters": [],
            "unsupported_scoring": {"ff": -2, "tf": -1, "unknown_rule": 3},
        }
    ]
    team = validate_config(cfg)["teams"][0]
    assert team["ignored_scoring"] == {"ff": -2, "tf": -1}
    assert team["unsupported_scoring"] == {"unknown_rule": 3}
    assert validate_config(cfg)["teams"][0] == team


def test_sleeper_suffix_variants_resolve_to_active_player():
    from fetch_data import resolve_player_ids, canonical_name

    result = resolve_player_ids(["Tim Hardaway", "Tim Hardaway Jr.", "Wendell Carter"])
    assert result["Tim Hardaway"] == result["Tim Hardaway Jr."] == 203501
    assert result["Wendell Carter"] == 1628976
    assert canonical_name("Gary Payton II") == canonical_name("Gary Payton")


@pytest.mark.parametrize(
    "assists,rebounds,expected", [(14, 19, 0), (15, 19, 3), (14, 20, 5), (16, 21, 8)]
)
def test_assist_rebound_milestones(assists, rebounds, expected):
    raw = rows()
    raw.loc[0, ["AST", "REB"]] = [assists, rebounds]
    raw["AST15"] = 999  # Recompute from observations, never trust old derived values.
    assert add_fantasy_points(raw, {"AST15": 3, "REB20": 5}).FP.iloc[0] == expected


def test_custom_bonus_import_and_saved_migration():
    from scoring import apply_scoring_policy, sleeper_bonus
    from storage import validate_config

    assert sleeper_bonus("bonus_ast_15p") == "AST15"
    assert sleeper_bonus("bonus_reb_20p") == "REB20"
    assert sleeper_bonus("bonus_stl_7p") == "STL7"
    assert sleeper_bonus("bonus_unknown_5p") is None
    team = {
        "weights": {"PTS": 1},
        "unsupported_scoring": {
            "bonus_ast_15p": 3,
            "bonus_reb_20p": 5,
            "oreb": 0.5,
            "dreb": 0.25,
            "pf": -0.2,
            "tf": -1,
        },
    }
    apply_scoring_policy(team)
    assert team["weights"] == {
        "PTS": 1,
        "AST15": 3,
        "REB20": 5,
        "OREB": 0.5,
        "DREB": 0.25,
        "PF": -0.2,
    }
    assert team["unsupported_scoring"] == {}
    before = dict(team)
    assert apply_scoring_policy(team) == before
    cfg = load_cfg()
    cfg["weights"] = {"AST15": 3, "REB20": 5, "STL7": 2}
    validate_config(cfg)


def test_rebound_split_and_missing_foul_policy():
    from scoring import fantasy_points

    raw = rows()
    weights = {"REB": 1, "OREB": 0.5, "DREB": 0.25, "PF": -0.2}
    assert add_fantasy_points(raw, weights).FP.iloc[0] == 13.75
    raw["OREB"], raw["DREB"], raw["PF"] = 2, 8, 3
    assert add_fantasy_points(raw, weights).FP.iloc[0] == pytest.approx(12.4)
    assert fantasy_points(raw.iloc[0], weights) == pytest.approx(12.4)
    assert add_fantasy_points(raw.drop(columns="DREB"), weights).FP.iloc[
        0
    ] == pytest.approx(13.15)
    assert (
        add_fantasy_points(raw.drop(columns=["OREB", "DREB"]), {"OREB": 1}).FP.iloc[0]
        == 5
    )


def test_milestone_requires_its_actual_stat():
    with pytest.raises(ValueError, match="AST"):
        add_fantasy_points(rows().drop(columns="AST"), {"AST15": 3})
