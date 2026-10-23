"""Load the historical Parquet fixtures into the normalized v2 store.

Reads the season games file plus the prior-season priors file under
``--fixtures`` and writes typed box scores into ``fact_game_logs`` (with
``dim_players``/``dim_teams``) in the experiment database. Everything is local;
the script never touches the network or the production ``lockin.sqlite3``
unless that file is explicitly requested as the destination.

    .venv/bin/python scripts/ingest_fixtures_to_db.py --db data/experiment.sqlite3
"""

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _load_game_store():
    """Import game_store.py by path so this script works from any directory."""
    spec = importlib.util.spec_from_file_location("game_store", ROOT / "game_store.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["game_store"] = module
    spec.loader.exec_module(module)
    return module


def _season_label(path):
    """Fixture folder name like ``2025-26`` -> the season of games.parquet."""
    name = Path(path).resolve().name
    if len(name) == 7 and name[4] == "-" and name.replace("-", "").isdigit():
        return name
    raise ValueError("Fixture directory must be named like '2025-26': " + str(path))


def _previous_season(season):
    year = int(season[:4])
    return f"{year - 1}-{str(year)[-2:]}"


def _records(store, season, frame):
    """Adapt a fixture DataFrame to the record dicts GameStore._ingest expects."""
    frame = frame.copy()
    frame["GAME_ID"] = frame.GAME_ID.astype(str).str.zfill(10)
    frame["GAME_DATE"] = pd.to_datetime(frame.GAME_DATE).dt.strftime("%Y-%m-%d")
    for column in ("TEAM_ID", "PLAYER_ID"):
        if column in frame:
            frame[column] = frame[column].astype(str)
    for row in frame.to_dict(orient="records"):
        yield store._record(season, row)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixtures", default=str(ROOT / "data/fixtures/2025-26"), help="fixture dir"
    )
    parser.add_argument(
        "--db",
        default=None,
        help="destination SQLite path (default LOCKIN_DB_PATH or data/experiment.sqlite3)",
    )
    args = parser.parse_args(argv)

    fixtures = Path(args.fixtures)
    manifest_path = fixtures / "manifest.json"
    season = _season_label(fixtures)
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        season = manifest.get("season") or season
    prior_season = _previous_season(season)

    store_cls = _load_game_store().GameStore
    destination = Path(
        args.db or os.environ.get("LOCKIN_DB_PATH") or ROOT / "data/experiment.sqlite3"
    )
    store = store_cls(destination)

    totals = {}
    with store.connect() as db:
        for filename, label in (
            ("games.parquet", season),
            ("priors.parquet", prior_season),
        ):
            path = fixtures / filename
            if not path.exists():
                continue
            frame = pd.read_parquet(path)
            store._ingest(db, _records(store, label, frame), reconcile=False)
            totals[label] = int(
                db.execute(
                    "SELECT COUNT(*) FROM fact_game_logs WHERE season=?", (label,)
                ).fetchone()[0]
            )
        violations = db.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise SystemExit(f"foreign_key_check failed: {violations[:5]}")
    print(f"ingested {totals} player-games into {destination}")
    if sum(totals.values()) < 50000:
        raise SystemExit("unexpectedly small ingestion; check fixtures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
