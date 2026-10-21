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


def blended_decision(current, previous, reference="2026-10-21", remaining=2):
    from test_lineup import projection_cfg

    return per_player_week_decision(
        "Test",
        current,
        {"PTS": 1},
        projection_cfg(),
        "A",
        reference=pd.Timestamp(reference),
        remaining_games=remaining,
        career_prior=999,
        previous_games=previous,
    )


@pytest.mark.parametrize(
    "reference,game_date", [("2026-10-21", "2026-10-20"), ("2027-02-17", "2027-02-16")]
)
def test_opening_or_injury_return_big_game_can_lock(reference, game_date):
    from test_lineup import logs, prior_logs

    prior = prior_logs()
    strong = blended_decision(logs([50], [game_date]), prior, reference)
    weak = blended_decision(logs([9], [game_date]), prior, reference)
    assert strong["decision"] == "LOCK" and strong["p_lock"] > 0.8
    assert weak["decision"] == "WAIT"
    assert strong["fp_mean_recent"] == 23  # 9 actual prior games, no extra shrinkage
    assert strong["sample_size"] == 10
    assert strong["baseline_current_season_games"] == 1
    assert strong["baseline_prior_season_games"] == 9
    assert strong["last_game_fp"] == 50 and len(strong["history"]) == 1


def test_lock_blend_excludes_future_and_cannot_lock_old_games():
    from test_lineup import logs, prior_logs

    current = logs([50], ["2026-10-20"])
    prior = prior_logs()
    before = blended_decision(current, prior)
    polluted_current = pd.concat([current, logs([999], ["2026-10-22"])])
    polluted_prior = pd.concat([prior, logs([999, 999], ["2026-10-19", "2027-03-01"])])
    assert before == blended_decision(polluted_current, polluted_prior)
    assert blended_decision(current, prior, remaining=None)["decision"] is None
    assert blended_decision(current, prior, remaining=0)["p_lock"] == 1
    assert (
        blended_decision(current, prior, reference="2026-10-28")["status"] == "NO_GAME"
    )
    empty = blended_decision(current.iloc[:0], prior)
    assert empty["status"] == "NO_HISTORY" and empty["decision"] is None


def test_lock_blend_transitions_and_handles_missing_or_invalid_history():
    from test_lineup import logs, prior_logs

    current = logs([9] * 10, pd.date_range(end="2026-10-20", periods=10))
    assert blended_decision(current, prior_logs()) == blended_decision(current, None)
    one = current.tail(1)
    assert blended_decision(one, prior_logs().drop(columns="PTS")) == blended_decision(
        one, None
    )
    sparse = blended_decision(one, prior_logs(2))
    assert sparse["sample_size"] == 3 and sparse["baseline_prior_season_games"] == 2


def test_lock_rarity_uses_prior_games_and_excludes_current_performance():
    from test_lineup import logs, prior_logs
    from model import rolling_baseline
    from season_history import blend_seasons

    previous = prior_logs(9).assign(STL=[0, 1, 2] * 3)
    current = logs([50], ["2026-10-20"]).assign(STL=8)
    history, _, _ = blend_seasons(current, previous, {"PTS": 1}, 10, "2026-10-21")
    baseline = rolling_baseline(add_fantasy_points(history, {"PTS": 1}))
    assert baseline["rare_means"]["STL"] == 1
    assert (
        rarity_boost(
            current.iloc[0],
            baseline["rare_means"],
            baseline["rare_stds"],
            ["STL"],
            1.75,
        )
        > 0
    )
