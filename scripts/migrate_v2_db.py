#!/usr/bin/env python3
"""Migrate the legacy JSON `games` store into the normalized v2 schema.

Reads `games.payload` records from a source SQLite file, normalizes dimensions
into dim_players/dim_teams, and writes typed box scores into fact_game_logs in
the destination database. Refresh metadata moves into dim_refreshes. The source
database is opened read-only and is never modified.

Usage:
    .venv/bin/python scripts/migrate_v2_db.py \
        --src data/lockin.sqlite3 --dest data/experiment.sqlite3
"""

import argparse
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from game_store import GameStore  # noqa: E402


def migrate(src, dest):
    src, dest = Path(src), Path(dest)
    if src.resolve() == dest.resolve():
        raise ValueError("Source and destination databases must differ.")
    if not src.is_file():
        raise FileNotFoundError("Source database not found: " + str(src))
    reader = sqlite3.connect("file:%s?mode=ro" % src, uri=True)
    try:
        tables = {
            row[0]
            for row in reader.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "games" not in tables:
            raise ValueError("No legacy games table in " + str(src))
        rows = reader.execute(
            """SELECT season, game_id, player_id, game_date, payload FROM games
            ORDER BY season, game_date, game_id, player_id"""
        ).fetchall()
        refreshes = (
            reader.execute(
                "SELECT season, refreshed_on, full_on, fetched_at FROM refreshes"
            ).fetchall()
            if "refreshes" in tables
            else []
        )
        managed = {
            "games",
            "refreshes",
            "dim_teams",
            "dim_players",
            "fact_game_logs",
            "dim_refreshes",
        }
        # Auxiliary stores sharing the file (forecast_snapshots, badge_* and any
        # future tables) are not normalized; carry them over verbatim instead
        # of leaving irreplaceable pregame forecast data behind.
        auxiliary = []
        for name, ddl in reader.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table'"
        ):
            if name in managed or name.startswith("sqlite_"):
                continue
            auxiliary.append(
                (name, ddl, reader.execute("SELECT * FROM %s" % name).fetchall())
            )
    finally:
        reader.close()

    payloads = []
    for season, gid, pid, day, payload in rows:
        record = json.loads(payload)
        record.update(GAME_ID=gid, PLAYER_ID=pid, GAME_DATE=day)
        payloads.append((season, record))

    store = GameStore(dest)
    with store.connect() as db:
        store._ingest(
            db,
            (store._record(season, row) for season, row in payloads),
            reconcile=False,
        )
        db.executemany(
            "INSERT OR REPLACE INTO dim_refreshes VALUES (?, ?, ?, ?)", refreshes
        )
        for name, ddl, aux_rows in auxiliary:
            db.execute(ddl.replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS", 1))
            cols = len(aux_rows[0]) if aux_rows else 1
            db.executemany(
                "INSERT OR IGNORE INTO %s VALUES (%s)" % (name, ",".join("?" * cols)),
                aux_rows,
            )

    expected_sums = tuple(
        sum(GameStore._number(row.get(stat)) for _, row in payloads)
        for stat in ("PTS", "REB", "AST")
    )
    with store.connect() as db:
        migrated = db.execute("SELECT COUNT(*) FROM fact_game_logs").fetchone()[0]
        actual_sums = db.execute(
            "SELECT SUM(pts), SUM(reb), SUM(ast) FROM fact_game_logs"
        ).fetchone()
        orphans = db.execute("PRAGMA foreign_key_check").fetchall()
        null_players = db.execute(
            """SELECT COUNT(*) FROM fact_game_logs g
            LEFT JOIN dim_players p ON g.player_id = p.player_id
            WHERE p.player_id IS NULL"""
        ).fetchone()[0]
    errors = []
    if migrated != len(payloads):
        errors.append(
            "player-game count %d != legacy rows %d" % (migrated, len(payloads))
        )
    if tuple(float(v or 0) for v in actual_sums) != expected_sums:
        errors.append("PTS/REB/AST sums %s != legacy %s" % (actual_sums, expected_sums))
    if orphans or null_players:
        errors.append(
            "foreign key violations: %d rows, %d unresolved players"
            % (len(orphans), null_players)
        )
    return {
        "src": str(src),
        "dest": str(dest),
        "rows": len(payloads),
        "migrated": migrated,
        "sums": actual_sums,
        "refreshes": len(refreshes),
        "auxiliary": {name: len(rows) for name, _, rows in auxiliary},
        "errors": errors,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--src", default="data/lockin.sqlite3")
    parser.add_argument("--dest", default="data/experiment.sqlite3")
    args = parser.parse_args(argv)
    report = migrate(args.src, args.dest)
    print(
        "Migrated %(migrated)d/%(rows)d player-games and %(refreshes)d refresh rows "
        "from %(src)s to %(dest)s." % report
    )
    print("PTS/REB/AST sums:", report["sums"])
    for name, count in sorted(report["auxiliary"].items()):
        print("Auxiliary table %s: %d rows" % (name, count))
    for error in report["errors"]:
        print("ERROR:", error, file=sys.stderr)
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
