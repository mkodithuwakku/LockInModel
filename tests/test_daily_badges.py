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
    from providers import FixtureProvider
    from engine import build_dashboard
    from storage import ROOT, validate_config
    import yaml

    provider = FixtureProvider()
    cfg = validate_config(yaml.safe_load((ROOT / "config.yaml").read_text()))
    team = dict(id="a", name="Sample A", players=["Jamal Murray"], starters=[])
    cfg["teams"] = [team, dict(team, id="b", name="Sample B", weights={"PTS": 10})]
    first = build_dashboard("replay", "2025-12-26", provider, cfg)
    a, b = [t["results"][0]["daily_badges"] for t in first["teams"]]
    assert a == b
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
