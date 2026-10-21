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


def test_missing_data_is_not_a_zero_projection():
    team = {"roster_positions": ["PG"]}
    result = recommend_lineup(team, [row()], {}, DATE)
    assert result["status"] == "partial" and result["total_projected_fp"] is None
    assert result["slots"][0]["player"] is None
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
            for pts, date in zip(points, dates or ["2026-10-19", "2026-10-20", DATE])
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
        == "current_season"
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
