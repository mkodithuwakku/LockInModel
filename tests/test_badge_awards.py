import datetime as dt

import pandas as pd
import pytest

from badge_awards import MILESTONES, fantasy_awards, raw_awards
from daily_badges import combine_badges
from test_daily_badges import game

DAY = "2025-12-26"


def row(pid="a", **stats):
    return game(pid, PTS=stats.pop("PTS", 20), MIN=stats.pop("MIN", 20), **stats)


def by_key(awards, key):
    return {pid: b for pid, badges in awards.items() for b in badges if b["key"] == key}


@pytest.mark.parametrize(
    "stat,threshold", [(s, n) for s, tiers in MILESTONES.items() for n in tiers]
)
def test_each_milestone_boundary_and_only_highest_tier(stat, threshold):
    frame = pd.DataFrame(
        [row("yes", **{stat: threshold}), row("no", **{stat: threshold - 1})]
    )
    awards = raw_awards(frame, DAY)
    key = f"milestone_{stat.lower()}_{threshold}"
    assert set(by_key(awards, key)) == {"yes"}
    assert (
        len(
            [
                b
                for b in awards["yes"]
                if b["key"].startswith(f"milestone_{stat.lower()}_")
            ]
        )
        == 1
    )
    assert by_key(awards, key)["yes"]["kind"] == "milestone"


def test_milestones_ignore_dnp_imputed_future_and_do_not_sum_games():
    frame = pd.DataFrame(
        [
            row("a", FG3M=3, GAME_ID="one"),
            row("a", FG3M=3, GAME_ID="two"),
            row("dnp", FG3M=10, MIN=0),
            row("future", FG3M=10, GAME_DATE=DAY),
        ]
    )
    assert not by_key(raw_awards(frame, DAY), "milestone_fg3m_5")
    assert not by_key(raw_awards(frame, DAY), "milestone_fg3m_10")
    frame = pd.DataFrame([row(FG3M=10)])
    frame.attrs["imputed_stats"] = ["FG3M"]
    assert not by_key(raw_awards(frame, DAY), "milestone_fg3m_10")


def test_lowest_margin_signed_ties_and_corrections():
    frame = pd.DataFrame(
        [
            row(str(i), AST=a, TOV=t)
            for i, (a, t) in enumerate([(2, 7), (1, 3), (0, 0), (2, 2), (4, 1)])
        ]
    )
    badges = by_key(raw_awards(frame, DAY), "careless")
    assert set(badges) == {"0", "1", "2", "3"}
    assert badges["0"]["value"] == -5 and badges["0"]["rank"] == 1
    assert badges["3"]["rank"] == 3 and badges["3"]["tied"]
    assert combine_badges(list(badges.values()))


def test_context_leaders_ties_zero_exclusion_and_league_scoring():
    frame = pd.DataFrame(
        [
            row("a", PTS=30, TOV=20, WL="W", MATCHUP="AAA vs. BBB"),
            row("b", PTS=20, TOV=0, WL="W", MATCHUP="AAA vs. BBB"),
            row("zero", PTS=0, WL="W", MATCHUP="AAA vs. BBB"),
            row("c", PTS=40, WL="L", MATCHUP="BBB @ AAA"),
            row("d", PTS=40, WL="L", MATCHUP="BBB @ AAA"),
        ]
    )
    result = fantasy_awards(frame, DAY, {"PTS": 1})
    assert set(by_key(result, "win_mvp")) == {"a"}
    assert set(by_key(result, "loss_mvp")) == {"c", "d"}
    assert set(by_key(result, "win_low")) == {"b"}
    assert set(by_key(result, "home_hero")) == {"a"}
    assert set(by_key(result, "away_villain")) == {"c", "d"}
    result = fantasy_awards(frame, DAY, {"PTS": 1, "TOV": -2})
    assert set(by_key(result, "win_mvp")) == {"b"}
    assert by_key(result, "win_low")["a"]["value"] == -10


def test_age_on_game_day_uses_fp_inclusive_boundaries_no_guessed_age():
    frame = pd.DataFrame(
        [
            row(pid, PTS=pts)
            for pid, pts in [
                ("32", 30),
                ("31", 100),
                ("23", 20),
                ("24", 200),
                ("missing", 300),
            ]
        ]
    )
    birthdays = {
        "32": "1993-12-25",
        "31": "1993-12-26",
        "23": "2001-12-26",
        "24": "2001-12-25",
        "missing": "invalid",
    }
    result = fantasy_awards(frame, DAY, {"PTS": 2}, birthdays=birthdays)
    assert by_key(result, "unc")["32"]["value"] == 60
    assert by_key(result, "new_gen")["23"]["value"] == 40
    assert not by_key(fantasy_awards(frame, DAY, {"PTS": 1}), "unc")


def test_schedule_final_context_handles_different_provider_ids_and_unknown_results():
    frame = pd.DataFrame(
        [row("a", TEAM_ABBREVIATION="AAA"), row("b", PTS=30, TEAM_ABBREVIATION="BBB")]
    )
    schedule = [
        dict(
            game_id="schedule-id",
            date="2025-12-25",
            home="AAA",
            away="BBB",
            status="complete",
            home_points=110,
            away_points=100,
        )
    ]
    assert not by_key(fantasy_awards(frame, DAY, {"PTS": 1}), "win_mvp")
    result = fantasy_awards(frame, DAY, {"PTS": 1}, calendar=schedule)
    assert set(by_key(result, "win_mvp")) == {"a"}
    assert set(by_key(result, "loss_mvp")) == {"b"}
    schedule[0]["status"] = "in_progress"
    assert not by_key(
        fantasy_awards(frame, DAY, {"PTS": 1}, calendar=schedule), "win_mvp"
    )


def test_streaks_strict_all_three_season_average_cutoff_and_last_night():
    rows = []
    for pid, scores in {
        "hot": [0, 20, 25, 30],
        "cold": [100, 20, 25, 30],
        "equal": [20, 20, 20, 20],
        "mixed": [20, 30, 10, 40],
    }.items():
        for i, pts in enumerate(scores):
            rows.append(row(pid, PTS=pts, GAME_DATE=f"2025-12-{22+i}", GAME_ID=str(i)))
    rows += [
        row("hot", PTS=9999, GAME_DATE=DAY),
        row("hot", PTS=9999, GAME_DATE="2024-12-24", GAME_ID="prior"),
    ]
    frame = pd.DataFrame(rows)
    result = fantasy_awards(frame, DAY, {"PTS": 1})
    assert set(by_key(result, "hot_streak")) == {"hot"}
    assert set(by_key(result, "cold_streak")) == {"cold"}
    assert by_key(result, "hot_streak")["hot"]["season_average"] == 18.75
    # Three-game samples cannot establish a strictly above/below-average streak.
    assert not by_key(
        fantasy_awards(frame[frame.GAME_DATE != "2025-12-22"], DAY, {"PTS": 1}),
        "hot_streak",
    )
    assert not by_key(
        fantasy_awards(frame[frame.GAME_DATE < DAY], "2025-12-27", {"PTS": 1}),
        "hot_streak",
    )
    corrected = pd.concat(
        [frame, pd.DataFrame([row("hot", PTS=1, GAME_DATE="2025-12-25", GAME_ID="3")])],
        ignore_index=True,
    )
    assert not by_key(fantasy_awards(corrected, DAY, {"PTS": 1}), "hot_streak")


def test_public_export_keeps_milestone_and_streak_explanation():
    from pages import public_report
    from test_pages import report

    raw = report()
    badge = dict(
        key="hot_streak",
        date="2025-12-25",
        rank=1,
        value=3,
        tied=False,
        kind="streak",
        season_average=20.5,
        scope="league_nba",
    )
    raw["teams"][0]["results"][0]["daily_badges"] = [dict(badge, birth_date="private")]
    assert public_report(raw)["teams"][0]["results"][0]["daily_badges"] == [badge]
