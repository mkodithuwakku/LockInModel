import pandas as pd

from season_review import season_review

ROSTER = [{"player_id": "1", "player": "One"}, {"player_id": "2", "player": "Two"}]


def games(n=32):
    return pd.DataFrame(
        [
            dict(
                PLAYER_ID="1",
                PLAYER_NAME="One",
                GAME_ID=str(i),
                GAME_DATE=pd.Timestamp("2025-10-21") + pd.Timedelta(days=i),
                PTS=i,
                REB=10,
                AST=10,
                STL=1,
                BLK=0,
                TOV=2,
                FG3M=0,
                FGM=2,
                FGA=4,
                FTM=1,
                FTA=2,
                MIN=30,
            )
            for i in range(n)
        ]
    )


def test_full_season_not_detail_window_and_league_scoring():
    frame = games()
    # Reused dataframe indices must not break best-game lookup.
    frame.index = [0] * len(frame)
    r = season_review(frame, ROSTER, {"PTS": 2, "TD": 5}, "2025-12-01")
    assert r["status"] == "ready" and r["appearances"] == 32
    assert r["total_fp"] == sum(2 * i + (5 if i >= 10 else 0) for i in range(32))
    assert r["covered_players"] == 1 and r["roster_count"] == 2
    assert r["stats"]["FG_PCT"] == r["stats"]["FT_PCT"] == 50
    assert r["players"][0]["change"] == 10
    assert r["players"][0]["best_fp"] == 67
    assert sum(w["games"] for w in r["weeks"]) == 32
    assert sum(w["total_fp"] for w in r["weeks"]) == r["total_fp"]
    assert len(r["game_log"]) == 32  # Full archive, not the 25-game card window.


def test_cutoff_prior_season_other_players_and_corrections():
    frame = games(3)
    correction = frame.iloc[[0]].assign(PTS=12)
    extra = pd.concat(
        [
            frame.iloc[[0]].assign(GAME_DATE=pd.Timestamp("2024-10-21"), GAME_ID="old"),
            frame.iloc[[0]].assign(PLAYER_ID="outside"),
            correction,
        ]
    )
    r = season_review(pd.concat([frame, extra]), ROSTER, {"PTS": 1}, "2025-10-22")
    assert r["appearances"] == 2 and r["total_fp"] == 13
    assert r["players"][0]["recent_games"] == 2
    assert r["players"][0]["change"] is None and r["players"][0]["spread"] is None
    assert r["players"][0]["share"] == 100
    assert r["season"] == "2025–26"


def test_empty_missing_and_negative_totals_remain_honest():
    assert (
        season_review(pd.DataFrame(), ROSTER, {"PTS": 1}, "2026-01-01")["total_fp"]
        is None
    )
    r = season_review(games(1), ROSTER, {"PTS": 1}, "2025-10-22", unavailable=True)
    assert r["status"] == "unavailable" and not r["players"]
    assert (
        season_review(games().drop(columns="PTS"), ROSTER, {"PTS": 1}, "2025-12-01")[
            "status"
        ]
        == "unavailable"
    )
    r = season_review(games(2), ROSTER, {"TOV": -1}, "2025-12-01")
    assert r["total_fp"] == -4 and r["top_three_share"] is None
    assert r["players"][0]["share"] is None
    r = season_review(
        games(2).drop(columns=["FGA", "FGM"]), ROSTER, {"PTS": 1}, "2025-12-01"
    )
    assert "FGM" not in r["stats"] and r["stats"]["FG_PCT"] is None


def test_completed_season_boundaries_and_public_allowlist():
    from pages import public_report
    from test_pages import report

    review = season_review(games(), ROSTER, {"PTS": 1}, "2026-11-01", season="2025")
    assert review["appearances"] == 32 and review["as_of"] == "2026-09-30"
    raw = report()
    raw["teams"][0]["season_review"] = review
    for obj in (review, review["stats"], review["players"][0], review["weeks"][0]):
        obj["secret"] = "PRIVATE"
    out = public_report(raw)["teams"][0]["season_review"]
    assert "PRIVATE" not in str(out)
    assert len(out["weeks"]) == len(review["weeks"])
    assert out["total_fp"] == review["total_fp"]


def _film_game(pid, name, date, points, gid):
    return dict(
        PLAYER_ID=pid,
        PLAYER_NAME=name,
        GAME_ID=gid,
        GAME_DATE=pd.Timestamp(date),
        PTS=points,
        REB=0,
        AST=0,
        STL=0,
        BLK=0,
        TOV=0,
        FG3M=0,
        FGM=0,
        FGA=0,
        FTM=0,
        FTA=0,
        MIN=30,
    )


def _film_rows():
    return [
        {
            "player_id": "1",
            "player": "Locker",
            "sleeper_id": "101",
            "positions": ["PG"],
            "roster_slot": "PG",
            "lineup_order": 0,
        },
        {
            "player_id": "2",
            "player": "Star",
            "sleeper_id": "102",
            "positions": ["PG"],
            "roster_slot": "BN",
            "lineup_order": 1,
        },
    ]


def _film_games():
    return pd.DataFrame(
        [
            _film_game("1", "Locker", "2026-10-21", 20, "g1"),
            _film_game("1", "Locker", "2026-10-24", 30, "g2"),
            _film_game("2", "Star", "2026-10-22", 50, "g3"),
        ]
    )


def _film_lock(fp=20, slot="PG", slot_index=0):
    return {
        "101": {
            "player_id": "101",
            "player_name": "Locker",
            "canonical_name": "locker",
            "roster_slot": slot,
            "slot_index": slot_index,
            "locked_fp": fp,
            "game_date": "2026-10-21",
        }
    }


def test_weekly_film_flags_locking_a_player_before_their_better_game():
    from season_review import weekly_film

    film = weekly_film(
        _film_games(),
        _film_rows(),
        ["PG", "UTIL"],
        _film_lock(),
        ["2026-10-20", "2026-10-26"],
        {"PTS": 1},
    )
    assert film["status"] == "ready"
    assert film["retained_fp"] == 70  # locked 20 + Star's 50 fills UTIL
    assert film["oracle_fp"] == 80  # Locker's 30 at PG + Star's 50 at UTIL
    assert film["regret_fp"] == 10 and film["efficiency"] == 87.5
    assert film["locked_count"] == 1 and film["clean_count"] == 0
    mistake = film["mistakes"][0]
    assert mistake["kind"] == "timing"
    assert mistake["better_player"] == "Locker"
    assert mistake["better_fp"] == 30 and mistake["better_date"] == "2026-10-24"
    assert mistake["cost_fp"] == 10


def test_weekly_film_flags_locking_the_wrong_player_for_a_slot():
    from season_review import weekly_film

    film = weekly_film(
        _film_games(),
        _film_rows(),
        ["PG"],
        _film_lock(),
        ["2026-10-20", "2026-10-26"],
        {"PTS": 1},
    )
    assert film["retained_fp"] == 20 and film["oracle_fp"] == 50
    assert film["regret_fp"] == 30
    mistake = film["mistakes"][0]
    assert mistake["kind"] == "player"
    assert mistake["better_player"] == "Star" and mistake["better_fp"] == 50
    assert mistake["cost_fp"] == 30


def test_weekly_film_clean_lock_and_empty_states():
    from season_review import weekly_film

    clean = weekly_film(
        _film_games(),
        _film_rows(),
        ["PG", "UTIL"],
        _film_lock(fp=30),
        ["2026-10-20", "2026-10-26"],
        {"PTS": 1},
    )
    assert clean["status"] == "ready" and clean["clean_count"] == 1
    assert clean["mistakes"] == [] and clean["retained_fp"] == 80
    unlocked = weekly_film(
        _film_games(),
        _film_rows(),
        ["PG", "UTIL"],
        {},
        ["2026-10-20", "2026-10-26"],
        {"PTS": 1},
    )
    assert unlocked["status"] == "ready" and unlocked["locked_count"] == 0
    assert unlocked["retained_fp"] == unlocked["oracle_fp"] == 80
    assert unlocked["mistakes"] == []
    empty = weekly_film(
        _film_games(),
        _film_rows(),
        ["PG", "UTIL"],
        _film_lock(),
        ["2026-11-02", "2026-11-08"],
        {"PTS": 1},
    )
    assert empty["status"] == "empty"
    assert (
        weekly_film(None, [], ["PG"], {}, ["2026-10-20", "2026-10-26"], {"PTS": 1})[
            "status"
        ]
        == "empty"
    )
    assert (
        weekly_film(
            _film_games(),
            _film_rows(),
            [],
            {},
            ["2026-10-20", "2026-10-26"],
            {"PTS": 1},
        )["status"]
        == "unavailable"
    )


def test_completed_roster_dashboard_reads_saved_season(monkeypatch):
    import engine
    from game_store import GameStore
    from storage import load_cfg

    calls = []

    def read(self, season):
        calls.append(season)
        return games(3)

    monkeypatch.setattr(GameStore, "read", read)
    monkeypatch.setattr(GameStore, "__init__", lambda self: None)
    cfg = load_cfg()
    cfg["teams"] = [
        dict(
            id="sample",
            name="Sample",
            players=["One"],
            starters=[],
            season="2025",
            league_status="complete",
            weights={"PTS": 2},
        )
    ]
    result = engine.roster_dashboard(cfg)["teams"][0]
    assert calls == ["2025-26"]
    assert result["season_review"]["total_fp"] == 6
    assert result["results"][0]["decision"] is None


def test_advanced_rates_use_attempts_and_preserve_missing_inputs():
    frame = games(5).assign(PTS=20, FGM=7, FGA=15, FG3M=3, FTM=3, FTA=4)
    frame.loc[0, "FGA"] = 30
    review = season_review(frame, ROSTER, {"PTS": 1}, "2025-12-01")
    player = review["players"][0]
    assert player["stats"]["EFG_PCT"] == round(42.5 / 90 * 100, 2)
    assert player["stats"]["TS_PCT"] == round(100 / (2 * (90 + 0.44 * 20)) * 100, 2)
    assert player["stats"]["AST_TOV"] == 5
    assert player["stats"]["FP_PER_MIN"] == 0.67
    assert player["floor_fp"] == player["ceiling_fp"] == 20
    missing = season_review(
        frame.drop(columns=["FTA"]).assign(TOV=0), ROSTER, {"PTS": 1}, "2025-12-01"
    )
    assert missing["players"][0]["stats"]["TS_PCT"] is None
    assert missing["players"][0]["stats"]["AST_TOV"] is None


def test_film_baselines_are_strictly_prior_and_corrected_games_count_once():
    from season_review import weekly_film

    history = pd.DataFrame(
        [
            _film_game("1", "Locker", "2026-10-15", 30, "p1"),
            _film_game("1", "Locker", "2026-10-16", 30, "p2"),
            _film_game("1", "Locker", "2026-10-17", 30, "p3"),
        ]
    )
    frame = pd.concat([history, _film_games(), _film_games().iloc[[0]].assign(PTS=10)])
    film = weekly_film(
        frame,
        _film_rows(),
        ["PG", "UTIL"],
        _film_lock(fp=10),
        ["2026-10-20", "2026-10-26"],
        {"PTS": 1},
    )
    assert len(film["performances"]) == 3
    first = next(
        p
        for p in film["performances"]
        if p["player_id"] == "1" and p["date"] == "2026-10-21"
    )
    assert first["baseline_fp"] == 30 and first["baseline_games"] == 3
    assert first["fp"] == 10 and first["delta"] == -20
    star = next(p for p in film["performances"] if p["player_id"] == "2")
    assert star["baseline_fp"] is None and star["delta"] is None
    assert film["regret_fp"] == 20


def test_new_comparison_and_film_fields_survive_public_export_without_private_data():
    from pages import public_report
    from test_pages import report
    from season_review import weekly_film

    raw = report()
    review = season_review(games(5), ROSTER, {"PTS": 1}, "2025-12-01")
    review["players"][0]["stats"]["secret"] = "PRIVATE"
    review["players"][0]["secret"] = "PRIVATE"
    raw["comparison"] = {
        "teams": [
            dict(review, team_id="test"),
            dict(review, team_id="archived", team_name="PRIVATE"),
        ]
    }
    raw["teams"][0]["film_review"] = weekly_film(
        _film_games(),
        _film_rows(),
        ["PG"],
        _film_lock(),
        ["2026-10-20", "2026-10-26"],
        {"PTS": 1},
    )
    raw["teams"][0]["film_review"]["performances"][0]["secret"] = "PRIVATE"
    out = public_report(raw)
    assert len(out["comparison"]["teams"]) == 1
    assert out["comparison"]["teams"][0]["players"][0]["stats"]["AST_TOV"] == 5
    assert len(out["teams"][0]["film_review"]["performances"]) == 3
    assert "PRIVATE" not in str(out)


def test_season_tape_components_context_and_prior_only_baselines():
    frame = games(12).assign(MATCHUP="BOS vs. NYK", WL="W")
    frame.loc[1, "MATCHUP"] = "BOS @ LAL"
    frame.loc[2, "MATCHUP"] = ""
    frame.loc[2, "WL"] = None
    weights = {"PTS": 2, "REB": 1.2, "TOV": -2, "DD": 3, "TD": 5, "PTS10": 2}
    review = season_review(frame, ROSTER, weights, "2025-12-01")
    log = review["game_log"]
    assert len(log) == 12
    assert log[0]["venue"] == "home" and log[0]["opponent"] == "NYK"
    assert log[1]["venue"] == "away" and log[1]["days_since_previous"] == 1
    assert log[2]["venue"] is None and log[2]["result"] is None
    assert log[0]["baseline_fp"] is None and log[2]["delta"] is None
    assert log[3]["baseline_fp"] == sum(g["fp"] for g in log[:3]) / 3
    assert log[-1]["baseline_games"] == 10
    for game in log:
        assert abs(sum(game["scoring"].values()) - game["fp"]) < 0.0001
    assert log[0]["double_double"] and not log[0]["triple_double"]
    assert log[10]["triple_double"]
    assert log[10]["scoring"]["PTS10"] == 2
    assert sum(g["fp"] for g in log) == review["total_fp"]
    assert (
        season_review(frame, ROSTER, weights, "2025-12-01", include_games=False)[
            "game_log"
        ]
        == []
    )


def test_season_tape_uses_effective_weights_and_retains_missing_box_stats():
    frame = games(5).drop(columns=["FGA", "FTA"])
    review = season_review(
        frame, ROSTER, {"PTS": 1, "OREB": 2, "DREB": 1, "PF": -1}, "2025-12-01"
    )
    assert review["game_log"][0]["stats"]["FGA"] is None
    assert review["game_log"][0]["stats"]["OREB"] is None
    assert review["game_log"][0]["scoring"]["REB"] == 15
    assert "PF" not in review["game_log"][0]["scoring"]
    assert len(review["scoring_notes"]) == 2
    from pages import public_report
    from test_pages import report

    raw = report()
    raw["teams"][0]["season_review"] = review
    review["game_log"][0]["secret"] = "PRIVATE"
    review["game_log"][0]["stats"]["secret"] = "PRIVATE"
    review["game_log"][0]["scoring"]["secret"] = "PRIVATE"
    review["scoring_rules"].append({"stat": "secret", "weight": "PRIVATE"})
    exported = public_report(raw)["teams"][0]["season_review"]
    assert len(exported["game_log"]) == 5
    assert "PRIVATE" not in str(exported)
