import datetime as dt

import pandas as pd

from badge_store import BadgeStore, NEGATIVE_KEYS
from test_daily_badges import game


def rows(day="2025-12-25", points=(40, 20, 10, 5)):
    return pd.DataFrame(
        [
            game(
                str(i),
                GAME_DATE=day,
                GAME_ID=day,
                PLAYER_NAME=f"Player {i}",
                TEAM_ABBREVIATION="BOS",
                PTS=pts,
                MIN=20,
                FG3M=5 if i == 0 else 0,
                FGA=10,
                FGM=5,
                WL="W",
                MATCHUP="BOS vs. NYK",
            )
            for i, pts in enumerate(points)
        ]
    )


def count(result, pid, key):
    return next(
        (p["counts"].get(key, 0) for p in result["players"] if p["player_id"] == pid), 0
    )


def test_backfill_idempotence_corrections_and_reopen(tmp_path, monkeypatch):
    store = BadgeStore(tmp_path / "history.sqlite3")
    frame = pd.concat([rows("2025-12-24"), rows()])
    first = store.sync(frame, "2025-12-26", {"PTS": 1})
    assert first["tracked_days"] == 2 and first["player_games"] == 8
    assert count(first, "0", "sniper") == 2
    assert count(first, "0", "milestone_pts_40") == 2
    assert store.sync(frame, "2025-12-26", {"PTS": 1}) == first
    assert BadgeStore(store.path).summary("2025-12-26", {"PTS": 1}) == first
    # Repeating unchanged observations does not rerun any badge calculations.
    import badge_store

    original = badge_store.previous_night_badges
    monkeypatch.setattr(
        badge_store,
        "previous_night_badges",
        lambda *args: (_ for _ in ()).throw(AssertionError("cache missed")),
    )
    assert store.sync(frame, "2025-12-26", {"PTS": 1}) == first
    monkeypatch.setattr(badge_store, "previous_night_badges", original)
    corrected = frame.copy()
    corrected.loc[
        (corrected.PLAYER_ID == "0") & (corrected.GAME_DATE == "2025-12-24"), "FG3M"
    ] = 0
    result = store.sync(corrected, "2025-12-26", {"PTS": 1})
    assert count(result, "0", "sniper") == 1
    assert count(result, "0", "milestone_fg3m_5") == 1
    assert result["total_awards"] == first["total_awards"] - 2


def test_correcting_earlier_game_rebuilds_later_streaks(tmp_path):
    store = BadgeStore(tmp_path / "history.sqlite3")
    frame = pd.concat(
        [rows(f"2025-12-{22+i}", (pts,)) for i, pts in enumerate([0, 20, 25, 30])]
    )
    first = store.sync(frame, "2025-12-26", {"PTS": 1})
    assert count(first, "0", "hot_streak") == 1
    frame.loc[frame.GAME_DATE == "2025-12-22", "PTS"] = 100
    result = store.sync(frame, "2025-12-26", {"PTS": 1})
    assert count(result, "0", "hot_streak") == 0
    assert count(result, "0", "cold_streak") == 1


def test_season_formula_and_reference_are_isolated(tmp_path):
    store = BadgeStore(tmp_path / "history.sqlite3")
    frame = pd.concat([rows("2024-12-25"), rows(), rows("2025-12-26")])
    first = store.sync(frame, "2025-12-26", {"PTS": 1})
    assert first["tracked_days"] == 1 and first["as_of"] == "2025-12-25"
    other = store.sync(frame, "2025-12-26", {"PTS": -1})
    assert count(first, "0", "win_mvp") == 1
    assert count(other, "3", "win_mvp") == 1
    assert store.summary("2025-12-26", {"PTS": 1}) == first
    assert store.summary("2025-12-26", {"PTS": 1}, "2024")["total_awards"] == 0
    store.sync(frame, "2025-12-27", {"PTS": 1})
    assert store.summary("2025-12-26", {"PTS": 1}) == first


def test_saved_forecasts_only_and_snapshot_changes_invalidate_day(tmp_path):
    store = BadgeStore(tmp_path / "history.sqlite3")
    first = store.sync(rows(), "2025-12-26", {"PTS": 1})
    assert first["forecast_player_games"] == 0
    assert count(first, "0", "overachiever") == 0
    store.save_forecasts(
        {"PTS": 1},
        "2025-12-25",
        {
            "0": dict(
                projected_fp=30, as_of="2025-12-25", projection_source="current_season"
            )
        },
        dt.datetime(2025, 12, 25, 20, tzinfo=dt.timezone.utc),
    )
    updated = store.sync(rows(), "2025-12-26", {"PTS": 1})
    assert updated["forecast_player_games"] == 1
    assert count(updated, "0", "overachiever") == 1
    assert count(updated, "1", "underachiever") == 0
    assert count(store.sync(rows(), "2025-12-26", {"PTS": 2}), "0", "overachiever") == 0


def test_duplicate_games_ties_classification_and_saved_failure(tmp_path):
    store = BadgeStore(tmp_path / "history.sqlite3")
    frame = rows(points=(40, 40, 40, 40))
    result = store.sync(pd.concat([frame, frame]), "2025-12-26", {"PTS": 1})
    assert result["player_games"] == 4
    assert all(p["counts"]["fire"] == 1 for p in result["players"])
    for p in result["players"]:
        assert p["negative"] == sum(
            n for k, n in p["counts"].items() if k in NEGATIVE_KEYS
        )
        assert p["total"] == sum(p["counts"].values())
        assert p["variety"] == len(p["counts"])
    assert "loss_mvp" not in NEGATIVE_KEYS
    saved = store.summary("2025-12-26", {"PTS": 1}, stale=True)
    assert saved["status"] == "saved" and saved["players"] == result["players"]
    assert store.sync(pd.DataFrame(), "2025-12-26", {"PTS": 1}) == result
    assert BadgeStore.saved_summary("2025-12-26", {"PTS": 1}, path=store.path) == result
    absent = tmp_path / "absent.sqlite3"
    assert (
        BadgeStore.saved_summary("2025-12-26", {"PTS": 1}, path=absent)["players"] == []
    )
    assert not absent.exists()


def test_public_report_allows_only_counts_and_display_metadata(tmp_path):
    from pages import public_report
    from test_pages import report

    raw = report()
    data = BadgeStore(tmp_path / "history.sqlite3").sync(
        rows(), "2025-12-26", {"PTS": 1}
    )
    data["private"] = "secret"
    data["players"][0]["birth_date"] = "private"
    data["players"][0]["counts"]["private"] = 7
    raw["teams"][0]["season_badges"] = data
    result = public_report(raw)["teams"][0]["season_badges"]
    assert "private" not in result and "birth_date" not in result["players"][0]
    assert "private" not in result["players"][0]["counts"]
