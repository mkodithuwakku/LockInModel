import pandas as pd
import pytest
from game_store import GameStore
from transport import DataUnavailable


def games(day="2026-10-20", gid="0022600001", points=20):
    return pd.DataFrame(
        [
            dict(
                GAME_DATE=day,
                GAME_ID=gid,
                PLAYER_ID=1,
                PLAYER_NAME="Example",
                PTS=points,
                REB=10,
                AST=15,
                STL=1,
                BLK=1,
                TOV=2,
                FG3M=2,
            )
        ]
    )


def test_append_corrections_daily_reuse_and_weekly_reconciliation(tmp_path):
    store = GameStore(tmp_path / "games.sqlite3")
    calls = []

    def fetch(since):
        calls.append(since)
        return games()

    assert len(store.refresh("2026-27", fetch, "2026-10-21")) == 1
    reopened = GameStore(store.path)
    reopened.refresh(
        "2026-27", lambda _: pytest.fail("Already refreshed today"), "2026-10-21"
    )

    def update(since):
        calls.append(since)
        return pd.concat([games(points=22), games("2026-10-21", "0022600002")])

    result = reopened.refresh("2026-27", update, "2026-10-22")
    assert len(result) == 2 and result.PTS.tolist() == [22, 20]
    reopened.refresh("2026-27", fetch, "2026-10-29")
    assert calls == [None, "2026-10-13", None]
    assert len(reopened.read("2026-27")) == 2  # No rows deleted by a partial response.
    assert reopened.read("2025-26").empty


@pytest.mark.parametrize("failure", ["network", "invalid", "empty"])
def test_failed_refresh_retains_rows_and_can_retry(tmp_path, failure):
    store = GameStore(tmp_path / "games.sqlite3")
    store.refresh("2026-27", lambda _: games(), "2026-10-21")

    def fail(_):
        if failure == "network":
            raise DataUnavailable("Offline")
        if failure == "empty":
            return games().iloc[:0]
        return games().drop(columns="GAME_ID")

    with pytest.raises(DataUnavailable):
        store.refresh("2026-27", fail, "2026-10-22")
    assert store.read("2026-27").PTS.tolist() == [20]
    result = store.refresh("2026-27", lambda _: games(points=25), "2026-10-22")
    assert result.PTS.tolist() == [25]


def test_seasons_are_isolated_and_missing_stats_never_committed(tmp_path):
    store = GameStore(tmp_path / "games.sqlite3")
    store.refresh("2025-26", lambda _: games(), "2026-10-21")
    store.refresh("2026-27", lambda _: games(points=30), "2026-10-21")
    assert store.read("2025-26").PTS.tolist() == [20]
    assert store.read("2026-27").PTS.tolist() == [30]
    with pytest.raises(DataUnavailable):
        store.refresh("2026-27", lambda _: games().drop(columns="REB"), "2026-10-22")
    assert store.read("2026-27").PTS.tolist() == [30]
