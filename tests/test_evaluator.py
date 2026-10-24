import pandas as pd
import pytest

from evaluator import (
    POLICIES,
    compute_forecast_metrics,
    evaluate_game_forecasts,
    evaluate_season_weekly_policy,
    simulate_weekly_lock,
)

# Weights {"PTS": 1} make each game's FP equal to its PTS, so expected scores are
# readable literals. The week of Monday 2026-10-19 runs through Sunday 2026-10-25.
WEIGHTS = {"PTS": 1}
CFG = {
    "decision": {
        "lookback_games": 10,
        "recent_days": 14,
        "decay": 0.92,
        "prior_weight_games": 12,
        "sd_floor_min": 4.0,
        "career_guard_scale": 0.6,
        "rookie_guard_fp": 17.5,
        "rare_z_threshold": 1.75,
        "rare_stats": ["BLK", "STL"],
        "lock_bias_if_rare": 0.15,
        "min_remaining_games_bias": 0.05,
        "conservative_mode": False,
    }
}


def frame(points, dates, pid="P1", name="Player One"):
    return pd.DataFrame(
        [
            dict(
                GAME_ID=f"{pid}-g{i}",
                PLAYER_ID=pid,
                PLAYER_NAME=name,
                GAME_DATE=day,
                PTS=pts,
                REB=0,
                AST=0,
                STL=0,
                BLK=0,
                TOV=0,
                FG3M=0,
                MIN=30,
            )
            for i, (day, pts) in enumerate(zip(dates, points))
        ]
    )


WEEK_DATES = ("2026-10-20", "2026-10-22", "2026-10-24")  # Tue, Thu, Sat


def week(points=(25, 55, 30), **kwargs):
    return frame(points, WEEK_DATES, **kwargs)


def test_forecast_metrics_perfect_and_offset_predictions():
    perfect = compute_forecast_metrics([10, 20, 30], [10, 20, 30])
    assert perfect == {
        "samples": 3,
        "mae": 0.0,
        "rmse": 0.0,
        "bias": 0.0,
        "correlation": 1.0,
    }
    offset = compute_forecast_metrics([15, 25, 35], [10, 20, 30])
    assert offset["mae"] == 5.0 and offset["bias"] == 5.0
    rmse_free = compute_forecast_metrics([10], [40])
    assert rmse_free["bias"] == -30.0 and rmse_free["correlation"] == 0.0
    assert compute_forecast_metrics([], [])["samples"] == 0


def test_evaluate_game_forecasts_pairs_profiles_and_counts_exclusions():
    games = frame([20, 30], ("2026-10-20", "2026-10-21"))
    profiles = {
        ("P1", "2026-10-20"): {
            "projected_fp": 18.0,
            "projected_stats": {"PTS": 18.0},
        },
        ("P1", "2026-10-21"): 35.0,
    }
    report = evaluate_game_forecasts(games, profiles, WEIGHTS)
    assert report["samples"] == 2 and report["excluded"] == 0
    assert report["fp"]["mae"] == 3.5 and report["fp"]["bias"] == -1.5
    assert report["stats"]["PTS"]["mae"] == 2.0

    del profiles[("P1", "2026-10-21")]
    report = evaluate_game_forecasts(games, profiles, WEIGHTS)
    assert report["samples"] == 1 and report["excluded"] == 1


def test_oracle_zero_regret_and_simple_policies_diverge():
    games = week()
    oracle = simulate_weekly_lock(games, WEIGHTS, CFG, "ORACLE")
    assert oracle["status"] == "resolved" and oracle["games"] == 3
    assert oracle["locked_fp"] == 55.0 and oracle["regret"] == 0.0
    assert oracle["efficiency"] == 100.0 and oracle["best_game_hit"]

    waiting = simulate_weekly_lock(games, WEIGHTS, CFG, "ALWAYS_WAIT")
    assert waiting["locked_fp"] == 30.0 and waiting["regret"] == 25.0
    assert waiting["forced_final_lock"] and waiting["locked_index"] == 2
    assert all(d["decision"] == "WAIT" for d in waiting["decisions"])

    threshold = simulate_weekly_lock(games, WEIGHTS, CFG, "THRESHOLD_40")
    assert threshold["locked_fp"] == 55.0 and threshold["regret"] == 0.0
    assert threshold["locked_index"] == 1 and not threshold["forced_final_lock"]
    assert [d["decision"] for d in threshold["decisions"]] == ["WAIT", "LOCK"]


def test_b0_baseline_locks_through_production_model_offline():
    result = simulate_weekly_lock(week(), WEIGHTS, CFG, "B0")
    assert result["status"] == "resolved" and result["locked_fp"] in (25.0, 55.0, 30.0)
    assert result["regret"] >= 0 and 0 <= result["efficiency"] <= 100
    assert len(result["decisions"]) >= 1
    assert all(
        {"date", "fp", "remaining", "decision"} <= set(d) for d in result["decisions"]
    )


def test_future_scores_cannot_change_earlier_decisions():
    baseline = simulate_weekly_lock(week(), WEIGHTS, CFG, "B0")
    mutated = week(points=(25, 55, 5000))
    changed = simulate_weekly_lock(mutated, WEIGHTS, CFG, "B0")
    cutoff = "2026-10-24"
    before = [d for d in baseline["decisions"] if d["date"] < cutoff]
    after = [d for d in changed["decisions"] if d["date"] < cutoff]
    assert before == after and before
    # The Thursday lock was already made before Saturday's mutation existed.
    assert baseline["locked_game_date"] == changed["locked_game_date"] == "2026-10-22"


def test_single_game_week_locks_terminal_game_for_every_policy():
    games = frame([17], ["2026-10-21"])
    for policy in POLICIES:
        result = simulate_weekly_lock(games, WEIGHTS, CFG, policy)
        assert result["locked_fp"] == 17.0 and result["regret"] == 0.0
        assert result["efficiency"] == 100.0


def test_empty_history_reports_no_games():
    result = simulate_weekly_lock(week().iloc[:0], WEIGHTS, CFG, "B0")
    assert result["status"] == "no_games"


def test_season_evaluation_aggregates_player_weeks(tmp_path):
    from game_store import GameStore

    store = GameStore(tmp_path / "games.sqlite3")
    season = "2026-27"
    players = pd.concat(
        [
            week(),
            frame([40, 10], ("2026-10-21", "2026-10-23"), pid="P2"),
        ]
    )
    store.refresh(season, lambda _: players, "2026-10-25")
    report = evaluate_season_weekly_policy(season, store, CFG, WEIGHTS)
    assert report["player_weeks"] == 2
    assert set(report["policies"]) == set(POLICIES)
    oracle = report["policies"]["ORACLE"]
    assert oracle["regret_total"] == 0.0 and oracle["efficiency_mean"] == 100.0
    wait = report["policies"]["ALWAYS_WAIT"]
    assert (
        wait["regret_total"] == 55.0
    )  # P1 waits past 55→30 (+25); P2 waits past 40→10 (+30)
    assert wait["total_fp"] == 40.0 and oracle["total_fp"] == 95.0
    b0 = report["policies"]["B0"]
    assert b0["player_weeks"] == 2 and b0["regret_total"] >= 0


def test_tune_ridge_ranks_grid_by_walkforward_mae():
    from evaluator import tune_ridge

    rows = []
    for day in pd.date_range("2026-01-01", periods=20, freq="D"):
        for p in range(10):
            if (p + day.day) % 2:
                continue
            team = f"T{p % 5}"
            rows.append(
                dict(
                    GAME_ID=f"g{day.day}-{p}",
                    PLAYER_ID=f"P{p}",
                    PLAYER_NAME=f"P{p}",
                    GAME_DATE=day,
                    TEAM_ABBREVIATION=team,
                    MATCHUP=f"{team} vs. T{(p + 1) % 5}",
                    WL="W",
                    MIN=30.0,
                    PTS=10 + p,
                    REB=5,
                    AST=4,
                    STL=1,
                    BLK=0,
                    TOV=2,
                    FG3M=1,
                    FGM=4,
                    FGA=9,
                    FTM=1,
                    FTA=2,
                    OREB=1,
                    DREB=0,
                    PF=1,
                    POSITION="G",
                )
            )
    games = pd.DataFrame(rows)
    grid = {"lam": (1.0, 50.0), "window": (5,), "decay": (0.92,)}
    results = tune_ridge(games, {"PTS": 1}, grid=grid)
    assert len(results) == 2
    assert all(r["samples"] > 0 for r in results)
    assert results[0]["mae"] <= results[1]["mae"]
    assert {"lam", "window", "decay", "mae", "rmse", "samples"} <= set(results[0])
    assert tune_ridge(games.iloc[:0], {"PTS": 1}) == []


PRE_WEEK = [str(d.date()) for d in pd.date_range("2026-09-01", periods=10)]


def team_games():
    """Role locks his only game Monday; Star still has Friday's game left."""
    return pd.concat(
        [
            frame([18] * 10 + [28], PRE_WEEK + ["2026-10-19"], pid="R1", name="Role"),
            frame([60] * 10 + [60], PRE_WEEK + ["2026-10-23"], pid="S1", name="Star"),
        ]
    )


def test_team_weekly_roster_beats_solo_when_star_contests_slot():
    from evaluator import simulate_team_weekly_locks

    slots, positions = ["UTIL"], {"R1": "PG", "S1": "PG"}
    args = dict(week_start="2026-10-19", positions=positions)
    solo = simulate_team_weekly_locks(
        team_games(), slots, WEIGHTS, CFG, "SOLO_B0", **args
    )
    roster = simulate_team_weekly_locks(
        team_games(), slots, WEIGHTS, CFG, "ROSTER_B0", **args
    )
    oracle = simulate_team_weekly_locks(
        team_games(), slots, WEIGHTS, CFG, "TEAM_ORACLE", **args
    )
    # Solo locks Role's 28 into the only slot, blocking Star's 60.
    assert solo["status"] == "resolved" and solo["total_fp"] == 28.0
    assert solo["oracle_fp"] == 60.0 and solo["regret"] == 32.0
    # Roster policy waits on Role because Star still contests UTIL.
    assert roster["total_fp"] == 60.0 and roster["regret"] == 0.0
    assert roster["locked_count"] == 1 and roster["regret"] < solo["regret"]
    role_decisions = [d for d in roster["decisions"] if d["player_id"] == "R1"]
    assert role_decisions[0]["decision"] == "WAIT"
    star_locks = [d for d in roster["decisions"] if d.get("slot") == "UTIL"]
    assert [d["player_id"] for d in star_locks] == ["S1"]
    # The oracle seats the weekly best into the slots directly.
    assert oracle["total_fp"] == 60.0 and oracle["efficiency"] == 100.0


def test_team_weekly_open_slots_leave_solo_decisions_intact():
    from evaluator import simulate_team_weekly_locks

    # Two UTIL slots for two players: nobody is displaced by either lock.
    positions = {"R1": "PG", "S1": "PG"}
    solo = simulate_team_weekly_locks(
        team_games(),
        ["UTIL", "UTIL"],
        WEIGHTS,
        CFG,
        "SOLO_B0",
        week_start="2026-10-19",
        positions=positions,
    )
    roster = simulate_team_weekly_locks(
        team_games(),
        ["UTIL", "UTIL"],
        WEIGHTS,
        CFG,
        "ROSTER_B0",
        week_start="2026-10-19",
        positions=positions,
    )
    assert solo["total_fp"] == roster["total_fp"] == 88.0
    assert roster["regret"] == 0.0


def test_evaluate_season_team_weekly_policy_uses_configured_rosters(tmp_path):
    from evaluator import evaluate_season_team_weekly_policy
    from game_store import GameStore

    store = GameStore(tmp_path / "games.sqlite3")
    season = "2026-27"
    # Star opens the season Monday; Role's only game is Wednesday; Star plays
    # again Friday. One UTIL slot means Role's Wednesday lock would block Star.
    week_only = pd.concat(
        [
            frame([60, 60], ["2026-10-19", "2026-10-23"], pid="S1", name="Star"),
            frame([28], ["2026-10-21"], pid="R1", name="Role"),
        ]
    )
    store.refresh(season, lambda _: week_only, "2026-10-25")
    cfg = dict(
        CFG,
        teams=[
            {
                "id": "t1",
                "name": "Test",
                "players": ["Role", "Star"],
                "starters": ["Role"],
                "roster_positions": ["UTIL"],
                "source": "local",
            }
        ],
    )
    positions = {"R1": "PG", "S1": "PG"}
    report = evaluate_season_team_weekly_policy(
        season,
        store,
        cfg,
        WEIGHTS,
        policies=["SOLO_B0", "ROSTER_B0", "TEAM_ORACLE"],
        positions=positions,
    )
    assert report["team_weeks"] == 1
    solo = report["policies"]["SOLO_B0"]
    roster = report["policies"]["ROSTER_B0"]
    oracle = report["policies"]["TEAM_ORACLE"]
    assert solo["total_fp"] == 28.0 and roster["total_fp"] == 60.0
    assert roster["regret_total"] == 0.0 and solo["regret_total"] == 32.0
    assert oracle["regret_total"] == 0.0 and oracle["efficiency_mean"] == 100.0
