import copy
import datetime as dt
import itertools
import random

import pandas as pd
import pytest

from lineup import (
    active_slots,
    eligible,
    optimal_assignment,
    project_players,
    recommend_lineup,
)

DATE = "2026-10-21"


def candidate(name, positions, fp):
    return {"player": name, "positions": positions, "projected_fp": fp}


def row(name="A", positions=None, **kwargs):
    return dict(
        player=name,
        player_id=name,
        positions=positions or ["PG"],
        roster_slot="BN",
        schedule_state="verified",
        week_games=[
            {"date": DATE, "status": "pre_game", "opponent": "BOS", "home": True}
        ],
        **kwargs
    )


def test_global_assignment_beats_greedy_and_retains_repeated_slots():
    players = [
        candidate("Flexible", ["PG", "SG"], 50),
        candidate("Point", ["PG"], 49),
        candidate("Wing", ["SG"], 10),
    ]
    chosen = optimal_assignment(["PG", "SG"], players)
    assert [players[i]["player"] for i in chosen] == ["Point", "Flexible"]
    assert (
        optimal_assignment(["UTIL", "UTIL", "UTIL", "UTIL"], players).count(None) == 1
    )
    assert len(set(i for i in chosen if i is not None)) == 2


def test_exact_assignment_matches_independent_exhaustive_search():
    rng = random.Random(184)
    for _ in range(60):
        slots = rng.choices(["PG", "SG", "G", "F", "C", "UTIL"], k=3)
        players = [
            candidate(
                str(i),
                rng.sample(["PG", "SG", "SF", "PF", "C"], k=2),
                rng.randint(-10, 60),
            )
            for i in range(5)
        ]
        assignment = optimal_assignment(slots, players)
        score = sum(players[i]["projected_fp"] for i in assignment if i is not None)
        brute = max(
            sum(players[i]["projected_fp"] for i in indexes if i is not None)
            for indexes in itertools.product([None] + list(range(5)), repeat=3)
            if len([i for i in indexes if i is not None])
            == len({i for i in indexes if i is not None})
            and all(
                i is None or eligible(players[i]["positions"], s)
                for s, i in zip(slots, indexes)
            )
        )
        assert score == brute
        assert all(
            i is None or eligible(players[i]["positions"], s)
            for s, i in zip(slots, assignment)
        )


def test_slots_follow_each_league_not_occupied_starters():
    assert active_slots({"source": "sleeper"}) is None
    assert active_slots(
        {
            "source": "sleeper",
            "roster_positions": ["PG", "SG", "UTIL", "UTIL", "BN", "IR", "TAXI"],
        }
    ) == ["PG", "SG", "UTIL", "UTIL"]
    assert active_slots({"starters": ["A", "B"]}) == ["UTIL", "UTIL"]
    assert (
        recommend_lineup({"roster_positions": ["UNKNOWN"]}, [], {}, DATE)["status"]
        == "unavailable"
    )
    assert optimal_assignment(["C"], [candidate("Guard", ["PG"], 100)]) == [None]
    assert optimal_assignment(["UTIL"], [candidate("Negative", ["C"], -1)]) == [None]
    assert optimal_assignment(["UTIL"], [candidate("Zero", [], 0)]) == [0]


def test_daily_plan_includes_bench_players_and_reports_exclusions():
    rows = [
        row("A"),
        row("B", ["SG"]),
        row("C", injury_status="Out"),
        row("D", injury_status="Questionable"),
        row("E"),
        row("F"),
        row("G"),
        row("H"),
    ]
    rows[4]["week_games"] = []
    rows[5]["roster_slot"] = "IR"
    rows[6]["week_games"][0]["status"] = "in_progress"
    rows[7]["week_games"][0]["status"] = "postponed"
    profiles = {
        p["player_id"]: {"projected_fp": 40 if p["player"] == "B" else 20} for p in rows
    }
    result = recommend_lineup(
        {"roster_positions": ["PG", "SG"]}, rows + [rows[0]], profiles, DATE
    )
    assert result["total_projected_fp"] == 60
    assert result["filled_slots"] == 2 and result["status"] == "partial"
    assert (
        result["eligible_players"] == 3
    )  # Questionable is eligible, duplicate A is not.
    reasons = {p["player"]: p["reason"] for p in result["bench"]}
    assert "Unavailable" in reasons["C"]
    assert reasons["E"] == "No game today"
    assert reasons["F"] == "Reserve slot"
    assert "started" in reasons["G"] and "postponed" in reasons["H"]


def test_idle_players_hold_open_slots_without_scoring():
    rows = [row("A"), row("B", ["SG"]), row("C", ["C"]), row("D", ["SG"])]
    for r in rows:
        r["week_games"] = []
    profiles = {r["player_id"]: {"projected_fp": 10} for r in rows}
    result = recommend_lineup(
        {"roster_positions": ["PG", "SG", "UTIL"]}, rows, profiles, DATE
    )
    assert result["status"] == "no_games" and result["filled_slots"] == 0
    assert [s["player"] for s in result["slots"]] == ["A", "B", "C"]
    assert all(s["off_day"] for s in result["slots"])
    assert all("No game today" in s["lineup_reason"] for s in result["slots"])
    # Idle players contribute nothing to the projected total.
    assert result["total_projected_fp"] == 0
    assert [(p["player"], p["reason"]) for p in result["bench"]] == [
        ("D", "No game today")
    ]


def test_off_day_fill_respects_positions_and_counts_only_playing_players():
    rows = [
        row("Playing", ["PG"]),
        row("Idle", ["C"]),
        row("IdleGuard", ["PG"]),
    ]
    rows[1]["week_games"] = []
    rows[2]["week_games"] = []
    profiles = {r["player_id"]: {"projected_fp": 30} for r in rows}
    result = recommend_lineup({"roster_positions": ["PG", "C"]}, rows, profiles, DATE)
    pg, c = result["slots"]
    assert pg["player"] == "Playing" and not pg.get("off_day")
    assert c["player"] == "Idle" and c["off_day"]
    assert result["filled_slots"] == 1 and result["total_projected_fp"] == 30
    # A guard cannot hold the center slot; it stays benched.
    assert {p["player"] for p in result["bench"]} == {"IdleGuard"}


def test_placeholder_fill_uses_played_or_unscheduled_but_never_out_or_reserve():
    playing = row("Playing", ["PG"])
    started = row("Started", ["C"])
    started["week_games"] = [{"date": DATE, "status": "in_progress"}]
    no_sched = row("NoSchedule", ["SG"])
    no_sched["schedule_state"] = "stale"
    no_sched["week_games"] = []
    out = row("Out", ["SF"], injury_status="Out")
    out["week_games"] = []
    reserve = row("Reserve", ["PF"])
    reserve["roster_slot"] = "IR"
    reserve["week_games"] = []
    rows = [playing, started, no_sched, out, reserve]
    profiles = {r["player_id"]: {"projected_fp": 20} for r in rows}
    result = recommend_lineup(
        {"roster_positions": ["PG", "SG", "C"]}, rows, profiles, DATE
    )
    assert [s["player"] for s in result["slots"]] == [
        "Playing",
        "NoSchedule",
        "Started",
    ]
    assert result["slots"][1]["off_day"] and result["slots"][2]["off_day"]
    assert "started or finished" in result["slots"][2]["lineup_reason"]
    # Only the playing player counts toward filled slots and the total.
    assert result["filled_slots"] == 1 and result["total_projected_fp"] == 20
    assert {p["player"] for p in result["bench"]} == {"Out", "Reserve"}


def test_missing_data_is_not_a_zero_projection():
    team = {"roster_positions": ["PG"]}
    result = recommend_lineup(team, [row()], {}, DATE)
    assert result["status"] == "partial" and result["total_projected_fp"] is None
    # A playing player without a projection holds the slot as a placeholder,
    # but never gains an invented projected score.
    slot = result["slots"][0]
    assert slot["player"] == "A" and slot["off_day"]
    assert slot.get("projected_fp") is None
    no_game = row()
    no_game["week_games"] = []
    assert recommend_lineup(team, [no_game], {}, DATE)["status"] == "no_games"
    unknown = row()
    unknown["schedule_state"] = "unavailable"
    assert recommend_lineup(team, [unknown], {}, DATE)["missing_inputs"] == 1
    assert (
        recommend_lineup(team, [row()], {}, DATE, blocked="Refresh failed")["slots"]
        == []
    )


def logs(points, dates=None):
    return pd.DataFrame(
        [
            dict(
                PLAYER_ID="A",
                PLAYER_NAME="A",
                GAME_DATE=pd.Timestamp(date),
                PTS=pts,
                REB=20,
                AST=15,
                STL=1,
                BLK=1,
                TOV=1,
                FG3M=2,
            )
            for pts, date in zip(
                points,
                dates if dates is not None else ["2026-10-19", "2026-10-20", DATE],
            )
        ]
    )


def test_projection_uses_league_formula_and_never_today_or_future():
    cfg = {
        "decision": {
            "recent_days": 14,
            "lookback_games": 10,
            "decay": 1,
            "prior_weight_games": 0,
        }
    }
    games = logs([10, 20, 999])
    weights = {"PTS": 1, "AST15": 5, "REB20": 7, "OREB": 1, "DREB": 1, "PF": -1}
    result = project_players(games, None, weights, cfg, DATE)["A"]
    assert result["projected_fp"] == 47  # 15 + 5 + 7 + 20; unavailable fouls omitted.
    assert result["last_played"] == "2026-10-20" and result["sample_size"] == 2
    games.loc[2, "PTS"] = 0
    assert project_players(games, None, weights, cfg, DATE)["A"] == result
    assert (
        project_players(games, None, {"PTS": 2}, cfg, DATE)["A"]["projected_fp"] == 30
    )
    fallback = logs([30], ["2026-04-01"])
    assert (
        project_players(games.iloc[0:0], fallback, {"PTS": 1}, cfg, DATE)["A"][
            "projection_source"
        ]
        == "prior_season"
    )
    assert (
        project_players(games, fallback, {"PTS": 1}, cfg, DATE)["A"][
            "projection_source"
        ]
        == "blended_seasons"
    )
    assert (
        project_players(games, None, {"FTM": 1}, cfg, DATE) == {}
    )  # Missing weighted data.


def test_prior_season_fallback_is_local_and_checksum_verified(tmp_path, monkeypatch):
    import hashlib
    import json
    import game_store
    import providers

    monkeypatch.setattr(providers, "ROOT", tmp_path)
    monkeypatch.setattr(game_store, "ROOT", tmp_path)
    folder = tmp_path / "data/fixtures/2025-26"
    folder.mkdir(parents=True)
    frame = logs([25], ["2026-04-01"])
    path = folder / "games.parquet"
    frame.to_parquet(path)
    (folder / "manifest.json").write_text(
        json.dumps(
            {"files": {"games.parquet": hashlib.sha256(path.read_bytes()).hexdigest()}}
        )
    )
    provider = providers.LiveProvider.__new__(providers.LiveProvider)
    provider.manifest = {"season": "2026-27"}
    assert len(provider.lineup_history()) == 1
    del provider._lineup_history
    path.write_bytes(b"corrupt")
    assert provider.lineup_history().empty


def projection_cfg(size=10, decay=1):
    return {
        "decision": {
            "lookback_games": size,
            "recent_days": 14,
            "decay": decay,
            "prior_weight_games": 12,
        }
    }


def prior_logs(count=20):
    return logs([20] * count, pd.date_range("2026-03-01", periods=count))


@pytest.mark.parametrize(
    "count, expected", [(1, 18.9), (3, 16.7), (9, 10.1), (10, 9.0)]
)
def test_current_games_gradually_replace_prior_games(count, expected):
    current = logs([9] * count, pd.date_range(end="2026-10-20", periods=count))
    result = project_players(current, prior_logs(), {"PTS": 1}, projection_cfg(), DATE)[
        "A"
    ]
    assert result["projected_fp"] == expected
    assert result["projected_stats"]["PTS"] == expected
    assert result["sample_size"] == 10
    if count < 10:
        assert result["projection_source"] == "blended_seasons"
        assert result["current_season_games"] == count
        assert result["prior_season_games"] == 10 - count
    else:
        assert result["projection_source"] == "current_season"
        # Once sufficient, changing prior-season results cannot affect the estimate.
        assert (
            project_players(
                current,
                prior_logs().assign(PTS=999),
                {"PTS": 1},
                projection_cfg(),
                DATE,
            )["A"]
            == result
        )


def test_blend_recency_and_milestones_use_actual_games_not_mean_thresholds():
    current = logs([9], ["2026-10-20"]).assign(AST=14)
    prior = prior_logs()
    weighted = project_players(
        current, prior, {"PTS": 1}, projection_cfg(4, 0.5), DATE
    )["A"]
    assert weighted["projected_fp"] == round((20 * (0.125 + 0.25 + 0.5) + 9) / 1.875, 2)
    bonus = project_players(
        current, prior, {"PTS": 1, "AST15": 5}, projection_cfg(), DATE
    )["A"]
    assert bonus["projected_stats"]["AST"] == 14.9
    assert bonus["projected_fp"] == 23.4  # 18.9 points + 9/10 games' five-point bonus.


def test_blend_respects_dates_missing_history_and_actual_sample_counts():
    current = logs([9, 999], ["2026-10-20", DATE])
    prior = pd.concat([prior_logs(), logs([999, 999], ["2026-10-19", "2026-10-22"])])
    result = project_players(current, prior, {"PTS": 1}, projection_cfg(), DATE)["A"]
    assert result["projected_fp"] == 18.9 and result["last_played"] == "2026-10-20"
    sparse = project_players(
        current, prior_logs(2), {"PTS": 1}, projection_cfg(), DATE
    )["A"]
    assert sparse["sample_size"] == 3 and sparse["prior_season_games"] == 2
    assert sparse["projected_fp"] == round(49 / 3, 2)
    for absent in (None, prior_logs().assign(PTS=-1)):
        result = project_players(current, absent, {"PTS": 1}, projection_cfg(), DATE)[
            "A"
        ]
        assert (
            result["projected_fp"] == 9
            and result["projection_source"] == "current_season"
        )


def test_blended_components_omit_unavailable_provider_splits():
    current = logs([9], ["2026-10-20"]).assign(PF=2, OREB=3, DREB=17)
    result = project_players(
        current,
        prior_logs(),
        {"PTS": 1, "OREB": 1, "DREB": 1, "PF": -1},
        projection_cfg(),
        DATE,
    )["A"]
    assert result["projection_source"] == "blended_seasons"
    assert result["projected_fp"] == 38.9
    assert (
        "PF" not in result["projected_stats"]
        and "OREB" not in result["projected_stats"]
    )
    assert result["scoring_notes"]
