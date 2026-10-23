"""Biweekly opponent-model evaluation, scheduled exactly like publication.py.

The launchd agent ticks every 15 minutes; run() performs work only when the
last completed check is at least INTERVAL_DAYS old, so a sleeping Mac runs
the overdue check right after wake — the same coalescing catch-up semantics
the daily publisher relies on. Each run:

1. Scores prospective B0-vs-Ridge game forecasts on the live season
   database, including any saved pregame forecast snapshots (read-only —
   evaluator.py never writes).
2. Replays weekly lock regret on the same live data.
3. Sweeps the lam x window x decay grid on the fixture database and records
   the best config for manual adoption under cfg['model'].

Results land in state/model_check.json (latest) and the append-only
state/model_check_history.jsonl (trend tracking). Nothing auto-applies tuned
values — the check recommends, a human adopts.
"""

import argparse
import datetime as dt
import fcntl
import json
import os
import plistlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LEDGER = ROOT / "state/model_check.json"
HISTORY = ROOT / "state/model_check_history.jsonl"
LIVE_DB = ROOT / "data/lockin.sqlite3"
EXPERIMENT_DB = ROOT / "data/experiment.sqlite3"
LABEL = "com.lockin.modelcheck"
INTERVAL = dt.timedelta(days=14)
RETRY_BACKOFF = dt.timedelta(hours=6)
UTC = dt.timezone.utc

from storage import load_cfg, read_json, write_json  # noqa: E402


def _season_frames(store, evaluator):
    """Latest-season games plus prior-season history from a GameStore."""
    import pandas as pd

    seasons = evaluator._store_seasons(store)
    if not seasons:
        return None, None, None
    season = seasons[-1]
    games = store.read(season)
    history = None
    if len(seasons) > 1:
        history = pd.concat(
            [store.read(s) for s in seasons if s != season], ignore_index=True
        )
    return season, games, history


def _live_sections(store, cfg, weights, evaluator):
    """Prospective scorecards against the real season (read-only)."""
    import pandas as pd
    from features import FeatureBuilder
    from model_ml import model_settings

    season, games, history = _season_frames(store, evaluator)
    if games is None or len(games) == 0:
        return {"season": season, "note": "no games stored"}
    positions = evaluator._store_positions(store)
    settings = model_settings(cfg)
    all_games = (
        pd.concat([history, games], ignore_index=True) if history is not None else games
    )
    builder = FeatureBuilder(
        all_games,
        positions=positions,
        window=settings["feature_window"],
        decay=settings["player_decay"],
        lookback=settings["player_lookback"],
    )
    game = evaluator.evaluate_game_backtest(
        games, cfg, weights, positions=positions, builder=builder, settings=settings
    )
    from forecast_store import ForecastStore

    profiles = {}
    fstore = ForecastStore(str(LIVE_DB))
    for day in sorted({str(d.date()) for d in pd.to_datetime(games.GAME_DATE)}):
        for pid, fp in fstore.read_forecasts(weights, day).items():
            profiles[(str(pid), day)] = fp
    if profiles:
        game["saved_forecasts"] = evaluator.evaluate_game_forecasts(
            games, profiles, weights
        )
    weekly = evaluator.evaluate_season_weekly_policy(
        season,
        store,
        cfg,
        weights,
        policies=["B0", "CHALLENGER_C1", "ORACLE"],
        history=history,
        positions=positions,
    )
    return {"season": season, "game": game, "weekly": weekly["policies"]}


def _tune_section(store, weights, evaluator):
    """lam x window x decay sweep on the fixture database."""
    import pandas as pd

    season, games, history = _season_frames(store, evaluator)
    if games is None or len(games) == 0:
        return {"season": season, "note": "no games stored"}
    positions = evaluator._store_positions(store)
    all_games = (
        pd.concat([history, games], ignore_index=True) if history is not None else games
    )
    results = evaluator.tune_ridge(
        all_games, weights, positions=positions, eval_games=games
    )
    return {"season": season, "results": results}


def build_report(cfg, now):
    """Assemble one biweekly report; per-section failures don't abort the rest."""
    import evaluator
    from game_store import GameStore

    weights = cfg.get("weights", {})
    report = {"ran_at": now.isoformat(), "sections": {}, "errors": []}
    try:
        report["sections"]["live"] = _live_sections(
            GameStore(LIVE_DB), cfg, weights, evaluator
        )
    except Exception as exc:
        report["errors"].append({"live": str(exc)})
    try:
        if EXPERIMENT_DB.exists():
            report["sections"]["tune"] = _tune_section(
                GameStore(EXPERIMENT_DB), weights, evaluator
            )
        else:
            report["sections"]["tune"] = {"note": "no fixture database"}
    except Exception as exc:
        report["errors"].append({"tune": str(exc)})
    return report


def summarize(report):
    """One-line headline for the launchd log."""
    parts = []
    live = (report.get("sections") or {}).get("live") or {}
    paired = (live.get("game") or {}).get("paired") or {}
    if paired.get("samples"):
        parts.append(
            "live MAE B0 {b:.2f} vs ridge {c:.2f} (n={n})".format(
                b=paired["B0"]["mae"],
                c=paired["CHALLENGER_C1"]["mae"],
                n=paired["samples"],
            )
        )
    weekly = live.get("weekly") or {}
    if weekly.get("B0") and weekly.get("CHALLENGER_C1"):
        parts.append(
            "weekly regret B0 {b:.1f} vs ridge {c:.1f}".format(
                b=weekly["B0"].get("regret_total", float("nan")),
                c=weekly["CHALLENGER_C1"].get("regret_total", float("nan")),
            )
        )
    results = ((report.get("sections") or {}).get("tune") or {}).get("results") or []
    if results:
        best = results[0]
        parts.append(
            "best tune lam={lam} window={window} decay={decay} (MAE {mae:.2f})".format(
                **best
            )
        )
    if report.get("errors"):
        parts.append("%d section error(s)" % len(report["errors"]))
    return "Model check complete" + (" — " + "; ".join(parts) if parts else ".")


def run(force=False, now=None):
    now = now or dt.datetime.now(UTC)
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER.with_suffix(".lock"), "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return "Model check already running."
        state = read_json(LEDGER, {})
        completed = state.get("completed_at")
        if (
            not force
            and completed
            and now - dt.datetime.fromisoformat(completed) < INTERVAL
        ):
            return "Model check not due yet."
        attempted = state.get("attempted_at")
        if (
            not force
            and not completed
            and attempted
            and now - dt.datetime.fromisoformat(attempted) < RETRY_BACKOFF
        ):
            return "Waiting for model check retry window."
        try:
            state["attempted_at"] = now.isoformat()
            write_json(LEDGER, state)
            report = build_report(load_cfg(), now)
            state.update(completed_at=now.isoformat(), report=report, error=None)
            write_json(LEDGER, state)
            with open(HISTORY, "a") as history:
                history.write(json.dumps(report, default=str) + "\n")
            return summarize(report)
        except Exception as exc:
            state.update(error=str(exc))
            write_json(LEDGER, state)
            raise


def launch_agent(root, python, home):
    return {
        "Label": LABEL,
        "ProgramArguments": [str(python), str(root / "model_check.py"), "run"],
        "WorkingDirectory": str(root),
        "RunAtLoad": True,
        # Missed calendar ticks coalesce into a run after wake; run() gates
        # actual work to the biweekly interval and the failure backoff.
        "StartCalendarInterval": [{"Minute": m} for m in (0, 15, 30, 45)],
        "ProcessType": "Background",
        "StandardOutPath": str(root / "logs/model_check.log"),
        "StandardErrorPath": str(root / "logs/model_check-error.log"),
        "EnvironmentVariables": {
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin",
            "HOME": str(home),
            "PYTHONUNBUFFERED": "1",
        },
    }


def install():
    if sys.platform != "darwin":
        raise ValueError("Automatic wake catch-up installation requires macOS.")
    root, home = ROOT.resolve(), Path.home()
    # Keep the venv executable path, not its resolved system-interpreter symlink.
    python = Path(sys.executable).absolute()
    (root / "logs").mkdir(exist_ok=True)
    target = home / "Library/LaunchAgents" / (LABEL + ".plist")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(plistlib.dumps(launch_agent(root, python, home)))
    target.chmod(0o600)
    domain = "gui/" + str(os.getuid())
    subprocess.run(["launchctl", "bootout", domain + "/" + LABEL], capture_output=True)
    subprocess.run(
        ["launchctl", "bootstrap", domain, str(target)], check=True, capture_output=True
    )
    return "Installed biweekly model check and wake catch-up: " + str(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["run", "install", "status"])
    parser.add_argument(
        "--force",
        action="store_true",
        help="Evaluate even if the biweekly interval has not elapsed",
    )
    args = parser.parse_args()
    try:
        if args.command == "install":
            message = install()
        elif args.command == "status":
            message = json.dumps(read_json(LEDGER, {}), indent=2)
        else:
            message = run(args.force)
        print(dt.datetime.now(UTC).isoformat(), message, flush=True)
    except Exception as exc:
        print(dt.datetime.now(UTC).isoformat(), str(exc), file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
