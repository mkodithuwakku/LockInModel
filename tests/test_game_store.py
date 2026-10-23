import json
import sqlite3

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


def test_explicit_refresh_updates_same_day_and_reconciles_provider_ids(tmp_path):
    store = GameStore(tmp_path / "games.sqlite3")
    store.refresh(
        "2026-27",
        lambda _: games(gid="sleeper-1").assign(SOURCE="Sleeper / Sportradar"),
        "2026-10-20",
    )
    # An explicit refresh sees corrected final stats instead of today's cached row.
    updated = store.refresh(
        "2026-27", lambda _: games(points=25), "2026-10-20", force=True
    )
    assert len(updated) == 1 and updated.PTS.tolist() == [25]
    assert updated.GAME_ID.tolist() == ["0022600001"]


def full_games():
    return pd.DataFrame(
        [
            dict(
                GAME_DATE="2026-10-20",
                GAME_ID="0022600001",
                PLAYER_ID="1630162",
                PLAYER_NAME="Anthony Edwards",
                TEAM_ID=1610612750,
                TEAM_ABBREVIATION="MIN",
                TEAM_NAME="Minnesota Timberwolves",
                MATCHUP="MIN vs. IND",
                WL="W",
                MIN=34.5,
                PTS=33,
                REB=5,
                AST=6,
                STL=2,
                BLK=1,
                TOV=3,
                FGM=12,
                FGA=21,
                FG3M=5,
                FG3A=9,
                FTM=4,
                FTA=5,
                OREB=1,
                DREB=4,
                PF=2,
            ),
            dict(
                GAME_DATE="2026-10-21",
                GAME_ID="sleeper-9",
                PLAYER_ID="sleeper:7788",
                PLAYER_NAME="Road Player",
                TEAM_ABBREVIATION="IND",
                MATCHUP="IND @ BOS",
                WL="L",
                MIN=28,
                PTS=18,
                REB=7,
                AST=4,
                STL=0,
                BLK=0,
                TOV=5,
                FGM=7,
                FGA=15,
                FG3M=2,
                FG3A=6,
                FTM=2,
                FTA=2,
                OREB=2,
                DREB=5,
                PF=4,
                SOURCE="Sleeper / Sportradar",
            ),
        ]
    )


def legacy_db(path, payloads, season="2026-27"):
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE games (
            season TEXT NOT NULL,
            game_id TEXT NOT NULL,
            player_id TEXT NOT NULL,
            game_date TEXT NOT NULL,
            payload TEXT NOT NULL,
            PRIMARY KEY (season, game_id, player_id)
        );
        CREATE TABLE refreshes (
            season TEXT PRIMARY KEY,
            refreshed_on TEXT NOT NULL,
            full_on TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        );
        """
    )
    for row in payloads:
        db.execute(
            "INSERT INTO games VALUES (?, ?, ?, ?, ?)",
            (
                season,
                str(row["GAME_ID"]),
                str(row["PLAYER_ID"]),
                row["GAME_DATE"],
                json.dumps(row),
            ),
        )
    db.execute(
        "INSERT INTO refreshes VALUES (?, ?, ?, ?)",
        (season, "2026-10-21", "2026-10-21", "2026-10-21T00:00:00+00:00"),
    )
    db.commit()
    db.close()


def load_migration_script():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts/migrate_v2_db.py"
    spec = importlib.util.spec_from_file_location("migrate_v2_db", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_env_var_selects_database_path(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCKIN_DB_PATH", str(tmp_path / "experiment.sqlite3"))
    store = GameStore()
    assert store.path == tmp_path / "experiment.sqlite3"
    monkeypatch.delenv("LOCKIN_DB_PATH")
    explicit = GameStore(tmp_path / "explicit.sqlite3")
    assert explicit.path == tmp_path / "explicit.sqlite3"


def test_normalized_schema_indexes_and_foreign_keys(tmp_path):
    store = GameStore(tmp_path / "games.sqlite3")
    with store.connect() as db:
        tables = {
            row[0]
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {
            "dim_teams",
            "dim_players",
            "fact_game_logs",
            "dim_refreshes",
        } <= tables
        indexes = {
            row[0]
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='index'")
        }
        assert {
            "idx_players_canonical",
            "idx_games_date",
            "idx_games_player",
            "idx_games_opponent",
        } <= indexes
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    with store.connect() as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                """INSERT INTO fact_game_logs
                (season, game_id, player_id, game_date)
                VALUES ('2026-27', '0022600099', 'ghost', '2026-10-20')"""
            )


def test_read_reconstructs_uppercase_frame_from_relational_rows(tmp_path):
    store = GameStore(tmp_path / "games.sqlite3")
    store.refresh("2026-27", lambda _: full_games(), "2026-10-22")
    frame = store.read("2026-27")
    expected = {
        "GAME_ID",
        "PLAYER_ID",
        "PLAYER_NAME",
        "GAME_DATE",
        "TEAM_ABBREVIATION",
        "MATCHUP",
        "WL",
        "MIN",
        "PTS",
        "REB",
        "AST",
        "STL",
        "BLK",
        "TOV",
        "FGM",
        "FGA",
        "FG3M",
        "FG3A",
        "FTM",
        "FTA",
        "OREB",
        "DREB",
        "PF",
        "SOURCE",
    }
    assert expected <= set(frame.columns)
    first, second = frame.iloc[0], frame.iloc[1]
    assert first.PLAYER_NAME == "Anthony Edwards"
    assert first.TEAM_ABBREVIATION == "MIN"
    assert first.MATCHUP == "MIN vs. IND"
    assert first.WL == "W" and first.MIN == 34.5 and first.PTS == 33
    assert second.MATCHUP == "IND @ BOS"
    assert second.SOURCE == "Sleeper / Sportradar"
    assert frame.GAME_DATE.dt.strftime("%Y-%m-%d").tolist() == [
        "2026-10-20",
        "2026-10-21",
    ]
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM dim_teams").fetchone()[0] == 3
        assert (
            db.execute(
                "SELECT COUNT(*) FROM dim_players WHERE canonical_name='anthony edwards'"
            ).fetchone()[0]
            == 1
        )


def test_legacy_payload_store_reads_identically_until_migrated(tmp_path):
    payloads = [
        dict(
            GAME_ID="0022600001",
            PLAYER_ID="1630162",
            PLAYER_NAME="Anthony Edwards",
            GAME_DATE="2026-10-20",
            TEAM_ABBREVIATION="MIN",
            MATCHUP="MIN vs. IND",
            WL="W",
            MIN=34.5,
            PTS=33,
            REB=5,
            AST=6,
            STL=2,
            BLK=1,
            TOV=3,
            FG3M=5,
            SOURCE="Sleeper / Sportradar",
        )
    ]
    legacy_path = tmp_path / "legacy.sqlite3"
    legacy_db(legacy_path, payloads)
    store = GameStore(legacy_path)
    assert store.legacy_mode
    legacy_frame = store.read("2026-27")
    assert legacy_frame.PTS.tolist() == [33]

    dest = tmp_path / "experiment.sqlite3"
    migrate_v2 = load_migration_script()

    report = migrate_v2.migrate(legacy_path, dest)
    assert report["errors"] == [] and report["migrated"] == 1

    migrated = GameStore(dest)
    new_frame = migrated.read("2026-27")
    columns = sorted(set(legacy_frame.columns) & set(new_frame.columns))
    pd.testing.assert_frame_equal(
        legacy_frame[columns].reset_index(drop=True),
        new_frame[columns].reset_index(drop=True),
        check_dtype=False,
    )


def test_refresh_drains_legacy_rows_into_fact_table(tmp_path):
    payloads = [
        dict(
            GAME_ID="sleeper-1",
            PLAYER_ID="1",
            PLAYER_NAME="Example",
            GAME_DATE="2026-10-19",
            TEAM_ABBREVIATION="MIN",
            MATCHUP="MIN vs. IND",
            PTS=20,
            REB=5,
            AST=5,
            STL=1,
            BLK=0,
            TOV=1,
            FG3M=1,
            SOURCE="Sleeper / Sportradar",
        )
    ]
    legacy_path = tmp_path / "legacy.sqlite3"
    legacy_db(legacy_path, payloads)
    store = GameStore(legacy_path)
    result = store.refresh(
        "2026-27", lambda _: games("2026-10-21", "0022600002", points=30), "2026-10-22"
    )
    assert result.PTS.tolist() == [20, 30]
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM fact_game_logs").fetchone()[0] == 2
    # The reconciled NBA observation for the same date replaces the fallback row.
    result = store.refresh(
        "2026-27",
        lambda _: games("2026-10-19", "0022600001", points=24),
        "2026-10-23",
        force=True,
    )
    assert result.GAME_ID.tolist() == ["0022600001", "0022600002"]
