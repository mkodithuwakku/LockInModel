import numpy as np
import pandas as pd
import pytest

from features import (
    COMPONENTS,
    FeatureBuilder,
    normalize_position,
    season_key,
    team_game_table,
)


def player_row(
    gid,
    pid,
    date,
    team,
    matchup,
    pts=10,
    reb=5,
    ast=4,
    stl=1,
    blk=0,
    tov=2,
    fg3m=1,
    fgm=4,
    fga=9,
    ftm=1,
    fta=2,
    oreb=1,
    min_=30.0,
    position="G",
    wl="W",
):
    return dict(
        GAME_ID=gid,
        PLAYER_ID=pid,
        PLAYER_NAME=f"Player {pid}",
        GAME_DATE=date,
        TEAM_ABBREVIATION=team,
        MATCHUP=matchup,
        WL=wl,
        MIN=min_,
        PTS=pts,
        REB=reb,
        AST=ast,
        STL=stl,
        BLK=blk,
        TOV=tov,
        FG3M=fg3m,
        FGM=fgm,
        FGA=fga,
        FTM=ftm,
        FTA=fta,
        OREB=oreb,
        DREB=0,
        PF=1,
        POSITION=position,
    )


def two_team_game(gid, date, **kw):
    """One A@B game: team A (home=0) vs team B (home=1), two players each."""
    return [
        player_row(gid, "A1", date, "AAA", "AAA @ BBB", **kw),
        player_row(gid, "A2", date, "AAA", "AAA @ BBB", **kw),
        player_row(gid, "B1", date, "BBB", "BBB vs. AAA", **kw),
        player_row(gid, "B2", date, "BBB", "BBB vs. AAA", **kw),
    ]


def test_team_game_table_possessions_and_pace_match_oliver_benchmark():
    # Team A: FGA 80, FTA 20, OREB 10, TOV 14, MIN 240
    # Team B: FGA 90, FTA 26, OREB 8,  TOV 18, MIN 240
    rows = [
        player_row(
            "g1",
            "A1",
            "2025-11-03",
            "AAA",
            "AAA @ BBB",
            fga=40,
            fta=10,
            oreb=5,
            tov=7,
            min_=120.0,
        ),
        player_row(
            "g1",
            "A2",
            "2025-11-03",
            "AAA",
            "AAA @ BBB",
            fga=40,
            fta=10,
            oreb=5,
            tov=7,
            min_=120.0,
        ),
        player_row(
            "g1",
            "B1",
            "2025-11-03",
            "BBB",
            "BBB vs. AAA",
            fga=45,
            fta=13,
            oreb=4,
            tov=9,
            min_=120.0,
        ),
        player_row(
            "g1",
            "B2",
            "2025-11-03",
            "BBB",
            "BBB vs. AAA",
            fga=45,
            fta=13,
            oreb=4,
            tov=9,
            min_=120.0,
        ),
    ]
    tg = team_game_table(pd.DataFrame(rows)).set_index("team")
    est_a = 80 + 0.44 * 20 - 10 + 14
    est_b = 90 + 0.44 * 26 - 8 + 18
    expected_poss = 0.5 * (est_a + est_b)
    assert tg.loc["AAA", "poss"] == pytest.approx(expected_poss)
    assert tg.loc["BBB", "poss"] == pytest.approx(expected_poss)
    # Pace = 48 * poss / (team_minutes/5); 240 team minutes -> pace == poss.
    assert tg.loc["AAA", "pace"] == pytest.approx(expected_poss)
    # Points allowed is the opponent's total.
    assert tg.loc["AAA", "pts_allowed"] == tg.loc["BBB", "pts_allowed"]


def test_rolling_opponent_metrics_exclude_same_day_and_future_games():
    rows = []
    # BBB plays four games on consecutive days; the last is a blowout.
    prior_stats = [(10, 5), (12, 4), (8, 6)]
    for i, (pts, tov) in enumerate(prior_stats):
        date = f"2025-11-{3 + i:02d}"
        rows += two_team_game(f"hist{i}", date, pts=pts, tov=tov)
    rows += two_team_game("big", "2025-11-06", pts=60, tov=0)
    builder = FeatureBuilder(pd.DataFrame(rows), window=15)

    # Features for AAA's game on 2025-11-06 must only use BBB games before then.
    target = pd.DataFrame(
        [
            dict(
                PLAYER_ID="A1",
                GAME_DATE="2025-11-06",
                TEAM_ABBREVIATION="AAA",
                MATCHUP="AAA @ BBB",
            )
        ]
    )
    feats = builder.features_for(target, cutoff=pd.Timestamp("2025-11-06"))
    assert len(feats) == 1
    # BBB conceded 10+12+8=30 PTS over 3 prior games; recheck by mutating the
    # target-day game and confirming identical features (strict cutoff).
    rows[-4:] = two_team_game("big", "2025-11-06", pts=999, tov=0)
    builder2 = FeatureBuilder(pd.DataFrame(rows), window=15)
    feats2 = builder2.features_for(target, cutoff=pd.Timestamp("2025-11-06"))
    for col in feats.columns:
        a, b = feats.iloc[0][col], feats2.iloc[0][col]
        assert (a == b) or (np.isnan(a) and np.isnan(b)), col


def test_rest_days_home_flag_and_back_to_back():
    rows = two_team_game("g1", "2025-11-03") + two_team_game("g2", "2025-11-04")
    builder = FeatureBuilder(pd.DataFrame(rows))
    targets = pd.DataFrame(
        [
            dict(
                PLAYER_ID="B1",
                GAME_DATE="2025-11-04",
                TEAM_ABBREVIATION="BBB",
                MATCHUP="BBB vs. AAA",
            ),
            dict(
                PLAYER_ID="A1",
                GAME_DATE="2025-11-04",
                TEAM_ABBREVIATION="AAA",
                MATCHUP="AAA @ BBB",
            ),
        ]
    )
    feats = builder.features_for(targets)
    home = feats.iloc[0]
    away = feats.iloc[1]
    assert home["is_home"] == 1.0 and away["is_home"] == 0.0
    assert home["rest_days"] == 0.0 and home["b2b"] == 1.0
    assert away["rest_days"] == 0.0 and away["b2b"] == 1.0


def test_recent_mean_uses_decay_and_ignores_future_games():
    rows = []
    # Player X plays three games; stat = index*10 so weights are checkable.
    for i, pts in enumerate((10, 20, 40)):
        date = f"2025-11-{3 + 2 * i:02d}"
        rows.append(player_row(f"x{i}", "X1", date, "AAA", "AAA @ BBB", pts=pts))
        rows.append(player_row(f"x{i}", "B9", date, "BBB", "BBB vs. AAA", pts=5))
    builder = FeatureBuilder(pd.DataFrame(rows), decay=0.5, lookback=10)
    matrix = builder.training_matrix()
    matrix = matrix.sort_values("GAME_DATE").reset_index(drop=True)
    player = matrix[matrix.PLAYER_ID == "X1"]
    # Row 3 features use games 1-2 with decay 0.5: (20*1 + 10*0.5)/1.5.
    third = player.iloc[2]
    assert third["recent_mean_PTS"] == pytest.approx((20 + 10 * 0.5) / 1.5)
    assert third["season_mean_PTS"] == pytest.approx(15.0)


def test_positional_concession_ratio_neutral_without_history():
    rows = two_team_game("g1", "2025-11-03")
    builder = FeatureBuilder(pd.DataFrame(rows))
    target = pd.DataFrame(
        [
            dict(
                PLAYER_ID="A1",
                GAME_DATE="2025-11-05",
                TEAM_ABBREVIATION="AAA",
                MATCHUP="AAA @ BBB",
            )
        ]
    )
    feats = builder.features_for(target)
    for s in COMPONENTS:
        assert feats.iloc[0]["pos_ratio_" + s] == 1.0
    assert feats.iloc[0]["pace_mult"] == 1.0
    assert feats.iloc[0]["defrtg_rel"] == 1.0


def test_position_and_season_key_helpers():
    assert normalize_position("pg") == "PG"
    assert normalize_position("Center") == "C"
    assert normalize_position("") is None
    assert normalize_position("UTIL") is None
    dates = pd.to_datetime(["2025-10-21", "2026-02-01", "2025-09-30"])
    assert list(season_key(dates)) == [2025, 2025, 2024]


def test_training_matrix_columns_and_neutral_first_game():
    rows = two_team_game("g1", "2025-11-03") + two_team_game("g2", "2025-11-05")
    builder = FeatureBuilder(pd.DataFrame(rows))
    matrix = builder.training_matrix()
    for s in COMPONENTS:
        assert f"recent_mean_{s}" in matrix and f"pos_ratio_{s}" in matrix
    assert {"pace_mult", "defrtg_rel", "is_home", "rest_days", "b2b"} <= set(
        matrix.columns
    )
    # First-game rows fall back to league means (finite, nonzero).
    assert np.isfinite(
        matrix[[c for c in matrix if c.startswith("recent_mean_")]].to_numpy()
    ).all()
