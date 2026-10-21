import pandas as pd
from pickups import analyze_player, find_pickups
from storage import load_cfg


def history():
    return pd.DataFrame(
        {
            "GAME_DATE": pd.date_range("2025-11-30", periods=20),
            "FP": [20] * 15 + [32] * 5,
            "MIN": [20] * 15 + [30] * 5,
            "FGM": [4] * 20,
            "FGA": [10] * 20,
            "FG3M": [1] * 20,
            "STL": [1] * 20,
            "BLK": [0] * 20,
        }
    )


def test_sustained_improvement_uses_separate_windows():
    result = analyze_player(history(), load_cfg())
    assert result["baseline_fp"] == 20 and result["recent_fp"] == 32
    assert result["qualifies"] and result["consistency"] == 1
    assert 20 < result["projected_fp"] < 32


def test_single_spike_does_not_qualify():
    h = history()
    h.FP = [20] * 19 + [80]
    assert not analyze_player(h, load_cfg())["qualifies"]


def test_tiny_history_not_ranked():
    assert analyze_player(history().tail(5), load_cfg()) is None


def test_candidates_and_scoring_are_specific_to_each_league():
    h = history().drop(columns="FP")
    h["PTS"] = [20] * 15 + [40] * 5
    for stat, value in [("REB", 5), ("AST", 5), ("TOV", 1), ("FTM", 2), ("FTA", 3)]:
        h[stat] = value
    h["PLAYER_ID"] = 1
    h["PLAYER_NAME"] = "Rising Player"
    h["TEAM_ABBREVIATION"] = "AAA"
    h["GAME_ID"] = [str(i) for i in range(len(h))]
    cfg = load_cfg()
    a = {
        "players": [],
        "starters": [],
        "owned_players": ["Rising Player"],
        "weights": {"PTS": 1},
        "ownership_complete": True,
    }
    b = {**a, "owned_players": []}
    assert find_pickups(h, a, cfg, "2025-12-19") == []
    candidates = find_pickups(h, b, cfg, "2025-12-19")
    assert candidates[0]["player"] == "Rising Player"
    c = {**b, "weights": {"PTS": 0.1}}
    assert (
        find_pickups(h, c, cfg, "2025-12-19") == []
    )  # Same player, different scoring, below lift threshold.


def test_available_directory_without_history_excludes_full_league_ownership():
    from pickups import available_players

    team = dict(
        ownership_complete=True,
        owned_players=["Rostered", "Reserve Jr."],
        players=["Mine"],
        owned_player_ids=["4"],
        synced_at="2026-10-21T06:00:00Z",
    )
    directory = {
        str(i): dict(full_name=name, active=True, fantasy_positions=["PG"], team="BOS")
        for i, name in enumerate(
            ["Available", "Rostered", "Reserve", "Mine", "Taxi", "Retired", "Team"]
        )
    }
    directory["5"]["active"] = False
    directory["6"]["fantasy_positions"] = ["TEAM"]
    pool = available_players(team, directory)
    assert [p["player"] for p in pool] == ["Available"]
    assert pool[0]["ownership_as_of"] == team["synced_at"]
    assert "projected_fp" not in pool[0]  # Missing analysis isn't zero.
    assert available_players({**team, "ownership_complete": False}, directory) == []


def test_available_players_show_actual_league_scored_values_before_trend_qualifies():
    from pickups import available_players
    from test_game_store import games

    team = dict(
        ownership_complete=True, owned_players=[], players=[], weights={"PTS": 2}
    )
    directory = {"1": dict(full_name="Example", active=True, fantasy_positions=["PG"])}
    item = available_players(team, directory, games(points=0), load_cfg())[0]
    assert item["recent_fp"] == 0 and item["games_recent"] == 1
    assert item["baseline_fp"] is None and item["lift"] is None
    assert (
        available_players(team, directory, games(points=12), load_cfg())[0]["recent_fp"]
        == 24
    )


def test_available_directory_survives_missing_weighted_stats():
    from pickups import available_players
    from test_game_store import games

    team = dict(
        ownership_complete=True, owned_players=[], players=[], weights={"FTA": 1}
    )
    directory = {"1": dict(full_name="Example", active=True, fantasy_positions=["PG"])}
    result = available_players(team, directory, games(), load_cfg())
    assert len(result) == 1 and "recent_fp" not in result[0]
