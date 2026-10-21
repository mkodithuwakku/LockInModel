import pandas as pd

from daily_badges import previous_night_badges


def game(pid, **stats):
    return {
        "PLAYER_ID": pid,
        "GAME_ID": "game",
        "GAME_DATE": "2025-12-25",
        "FG3M": 0,
        "FGM": 0,
        "FGA": 0,
        "REB": 0,
        "STL": 0,
        "BLK": 0,
        "MIN": 0,
        "AST": 0,
        "TOV": 0,
        **stats,
    }


def test_all_categories_use_observations_and_misses_are_attempts_minus_makes():
    frame = pd.DataFrame(
        [
            game(
                "a",
                FG3M=7,
                FGM=12,
                FGA=22,
                REB=14,
                STL=4,
                BLK=3,
                MIN=38.5,
                AST=11,
                TOV=6,
            )
        ]
    )
    badges = previous_night_badges(frame, "2025-12-26")["a"]
    values = {b["key"]: b["value"] for b in badges}
    assert values == dict(
        sniper=7,
        fire=12,
        bricks=10,
        boards=14,
        thief=4,
        rejection=3,
        runner=38.5,
        dime=11,
        sandwich=6,
    )
    assert all(b["rank"] == 1 and b["date"] == "2025-12-25" for b in badges)
    assert previous_night_badges(frame, "2025-12-25") == {}
    assert previous_night_badges(frame, "2025-12-27") == {}


def test_competition_ranks_include_ties_at_third_not_three_distinct_scores():
    frame = pd.DataFrame(
        [game(str(i), FG3M=n) for i, n in enumerate([9, 7, 5, 5, 4, 0])]
    )
    awards = previous_night_badges(frame, "2025-12-26")
    assert set(awards) == {"0", "1", "2", "3"}
    assert awards["2"][0]["rank"] == 3 and awards["2"][0]["tied"]
    frame.loc[1, "FG3M"] = 9
    awards = previous_night_badges(frame, "2025-12-26")
    assert awards["2"][0]["rank"] == 3


def test_duplicates_corrections_and_other_dates_do_not_change_daily_totals():
    frame = pd.DataFrame(
        [
            game("a", FG3M=1),
            game("a", FG3M=6),
            game("a", FG3M=90, GAME_DATE="2025-12-26"),
            game("a", FG3M=90, GAME_DATE="2025-12-24"),
        ]
    )
    assert previous_night_badges(frame, "2025-12-26")["a"][0]["value"] == 6


def test_missing_bad_and_imputed_values_do_not_create_leaders():
    frame = pd.DataFrame(
        [game("a", FG3M=3, AST=2, FGM=4, FGA=3), game("b", FG3M=float("nan"), AST=1)]
    )
    frame.attrs["imputed_stats"] = ["AST"]
    result = previous_night_badges(frame, "2025-12-26")
    assert [b["key"] for b in result["a"]] == ["fire"]
    assert "b" not in result
    assert previous_night_badges(pd.DataFrame([game("a")]), "2025-12-26") == {}
    assert previous_night_badges(pd.DataFrame(), "2025-12-26") == {}


def test_engine_uses_nba_pool_not_roster_or_league_scoring(monkeypatch):
    from types import SimpleNamespace
    from engine import build_dashboard
    from storage import ROOT, validate_config
    import yaml

    provider = SimpleNamespace(
        manifest={"week_start": "2025-12-22", "week_end": "2025-12-28"},
        games=pd.DataFrame(
            [
                game(
                    "rostered",
                    PLAYER_NAME="Roster Player",
                    MIN=40,
                    PTS=10,
                    FGM=5,
                    FGA=10,
                    FTM=0,
                    FTA=0,
                ),
                game(
                    "outside",
                    PLAYER_NAME="Other Player",
                    MIN=42,
                    PTS=12,
                    FGM=6,
                    FGA=10,
                    FTM=0,
                    FTA=0,
                ),
            ]
        ),
        schedule=pd.DataFrame(),
        prior=lambda *_: 20,
        remaining=lambda *_: 1,
    )
    cfg = validate_config(yaml.safe_load((ROOT / "config.yaml").read_text()))
    team = dict(id="a", name="Sample A", players=["Roster Player"], starters=[])
    cfg["teams"] = [team, dict(team, id="b", name="Sample B", weights={"PTS": 10})]
    first = build_dashboard("replay", "2025-12-26", provider, cfg)
    a, b = [t["results"][0]["daily_badges"] for t in first["teams"]]
    assert [x for x in a if not x.get("scope")] == [x for x in b if not x.get("scope")]
    assert (
        next(x for x in a if x["key"] == "efficient")["value"]
        != next(x for x in b if x["key"] == "efficient")["value"]
    )
    assert next(x for x in a if x["key"] == "runner")["rank"] == 2
    provider.stats_error = "Unavailable"
    failed = build_dashboard("replay", "2025-12-26", provider, cfg)
    assert not failed["teams"][0]["results"][0]["daily_badges"]


def test_public_export_keeps_only_badge_display_fields():
    from pages import public_report
    from test_pages import report

    raw = report()
    award = dict(key="sniper", date="2025-12-25", rank=1, value=9, tied=False)
    raw["teams"][0]["results"][0]["daily_badges"] = [dict(award, secret="private")]
    assert public_report(raw)["teams"][0]["results"][0]["daily_badges"] == [award]


def test_free_throw_and_missed_three_leaders_require_valid_observations():
    frame = pd.DataFrame(
        [game("a", FTM=8, FG3A=12, FG3M=3), game("b", FTM=7, FG3A=5, FG3M=2)]
    )
    awards = previous_night_badges(frame, "2025-12-26")
    assert next(x for x in awards["a"] if x["key"] == "heartbreak")["value"] == 9
    assert next(x for x in awards["a"] if x["key"] == "merchant")["rank"] == 1
    frame.loc[1, "FG3A"] = 1
    assert all(
        x["key"] != "heartbreak"
        for bs in previous_night_badges(frame, "2025-12-26").values()
        for x in bs
    )


def test_fantasy_badges_rank_league_scores_signed_errors_and_rates():
    from daily_badges import fantasy_night_badges

    frame = pd.DataFrame(
        [
            game(str(i), PTS=pts, MIN=minutes)
            for i, (pts, minutes) in enumerate(
                [(20, 10), (30, 30), (8, 20), (0, 12), (5, 10), (60, 0)]
            )
        ]
    )
    saved = {"0": 10, "1": 40, "2": 20, "3": 0, "4": 10, "5": 0}
    awards = fantasy_night_badges(frame, "2025-12-26", {"PTS": 1}, saved)

    def badge(pid, key):
        return next(x for x in awards[pid] if x["key"] == key)

    assert badge("0", "overachiever")["value"] == 10
    assert badge("2", "underachiever")["rank"] == 1
    assert badge("2", "underachiever")["value"] == 12
    assert badge("0", "efficient")["value"] == 2
    assert badge("3", "inefficient")["value"] == 0
    assert badge("3", "inefficient")["rank"] == 1
    assert "5" not in awards
    assert badge("2", "underachiever")["forecast_count"] == 5
    assert badge("2", "underachiever")["player_count"] == 5
    assert all(
        b["key"] not in {"overachiever", "underachiever"}
        for bs in fantasy_night_badges(frame, "2025-12-26", {"PTS": 1}).values()
        for b in bs
    )
    negative = fantasy_night_badges(frame, "2025-12-26", {"PTS": -1}, saved)
    assert next(x for x in negative["0"] if x["key"] == "inefficient")["value"] == -2


def test_fantasy_rates_ties_corrections_and_dates():
    from daily_badges import fantasy_night_badges

    rows = [game(str(i), PTS=n, MIN=10) for i, n in enumerate([90, 70, 50, 50, 40])]
    frame = pd.DataFrame(
        rows + [dict(rows[0], PTS=999, GAME_DATE="2025-12-26"), dict(rows[0], PTS=80)]
    )
    awards = fantasy_night_badges(frame, "2025-12-26", {"PTS": 1}, {"0": 10})
    assert next(x for x in awards["0"] if x["key"] == "efficient")["value"] == 8
    assert next(x for x in awards["3"] if x["key"] == "efficient")["rank"] == 3
    assert next(x for x in awards["3"] if x["key"] == "efficient")["tied"]
    assert (
        next(x for x in awards["0"] if x["key"] == "overachiever")["forecast_count"]
        == 1
    )
    assert (
        fantasy_night_badges(frame.drop(columns="MIN"), "2025-12-26", {"PTS": 1}) == {}
    )


def test_live_engine_uses_saved_forecasts_and_exports_comparison(monkeypatch):
    from types import SimpleNamespace
    from engine import build_dashboard
    from storage import load_cfg
    from pages import public_report

    cfg = load_cfg()
    cfg["teams"] = [
        dict(
            id="sample",
            name="Sample",
            players=["Sample Player"],
            starters=[],
            weights={"PTS": 2},
        )
    ]
    frame = pd.DataFrame(
        [
            game("a", PLAYER_NAME="Sample Player", PTS=10, MIN=20),
            game("b", PLAYER_NAME="Other Player", PTS=20, MIN=20),
        ]
    )
    provider = SimpleNamespace(
        games=frame,
        manifest={"season": "2025-26"},
        calendar=None,
        prior=lambda *_: None,
        remaining_for_team=lambda *_: 2,
    )
    reads = []

    def read(weights, day):
        reads.append((weights, str(day)))
        return {"a": 5, "b": 10}

    store = SimpleNamespace(read_forecasts=read)
    report = public_report(
        build_dashboard("live", "2025-12-26", provider, cfg, forecast_store=store)
    )
    badge = next(
        b
        for b in report["teams"][0]["results"][0]["daily_badges"]
        if b["key"] == "overachiever"
    )
    assert reads == [({"PTS": 2}, "2025-12-25")]
    assert badge["rank"] == 2 and badge["value"] == 15
    assert badge["actual_fp"] == 20 and badge["projected_fp"] == 5
    assert badge["forecast_count"] == badge["player_count"] == 2


def test_multiple_games_compare_total_fp_to_per_game_forecast_times_games():
    from daily_badges import fantasy_night_badges

    frame = pd.DataFrame(
        [
            game("a", PTS=10, MIN=10, GAME_ID="first"),
            game("a", PTS=30, MIN=10, GAME_ID="second"),
        ]
    )
    badges = fantasy_night_badges(frame, "2025-12-26", {"PTS": 1}, {"a": 15})["a"]
    over = next(b for b in badges if b["key"] == "overachiever")
    assert over["value"] == 10 and over["projected_fp"] == 30
