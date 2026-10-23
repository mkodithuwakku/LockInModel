"""Offline evaluation harness: forecast error metrics and weekly lock regret.

Scorecard 1 (game forecasts) compares saved pregame projections against observed
fantasy points. Scorecard 2 (weekly lock policy) replays sequential decisions
across a Monday-Sunday matchup week without future data leakage: at each game
day t only observations up to t are exposed, a LOCK freezes that game's score,
a WAIT advances, and an unlocked week retains the final played game.

All policies share identical timing and terminal rules. The production model is
benchmarked as B0 by calling decide.per_player_week_decision as a black box with
remaining_games and career_prior supplied explicitly, so evaluation never makes
network calls.
"""

import argparse
import json

import numpy as np
import pandas as pd

from decide import per_player_week_decision
from fetch_data import (
    _season_for_today,
    get_week_bounds,
    last_n_days,
    normalize_stats_for_scoring,
)
from model import probability_future_beats_current, rolling_baseline
from scoring import add_fantasy_points

POLICIES = ("B0", "RAW_NORMAL", "ALWAYS_WAIT", "THRESHOLD_40", "ORACLE")


def compute_forecast_metrics(actuals, predictions):
    """MAE, RMSE, signed bias, and Pearson r for paired numeric series."""
    actuals = np.asarray(list(actuals), dtype=float)
    predictions = np.asarray(list(predictions), dtype=float)
    valid = np.isfinite(actuals) & np.isfinite(predictions)
    actuals, predictions = actuals[valid], predictions[valid]
    if not actuals.size:
        return {
            "samples": 0,
            "mae": None,
            "rmse": None,
            "bias": None,
            "correlation": None,
        }
    errors = actuals - predictions
    mae = float(np.mean(np.abs(errors)))
    rmse = float(np.sqrt(np.mean(errors**2)))
    bias = float(np.mean(errors))
    corr = 0.0
    if actuals.size > 1 and np.std(predictions) > 0:
        corr = float(np.corrcoef(actuals, predictions)[0, 1])
        if not np.isfinite(corr):
            corr = 0.0
    return {
        "samples": int(actuals.size),
        "mae": round(mae, 2),
        "rmse": round(rmse, 2),
        "bias": round(bias, 2),
        "correlation": round(corr, 3),
    }


def _profile_value(profile, field):
    if isinstance(profile, dict):
        return profile.get(field)
    return profile if field == "projected_fp" else None


def evaluate_game_forecasts(games_df, profiles, weights):
    """Pair observed games with saved pregame projections and score the error.

    profiles maps a player key to a projected FP float or a profile dict with
    projected_fp/projected_stats. Keys may be player_id or (player_id, date)
    tuples; the dated key wins when both exist.
    """
    empty = {
        "samples": 0,
        "excluded": 0,
        "fp": compute_forecast_metrics([], []),
        "stats": {},
    }
    if games_df is None or len(games_df) == 0:
        return empty
    scored = add_fantasy_points(normalize_stats_for_scoring(games_df), weights)
    actual_fp, predicted_fp, excluded = [], [], 0
    stat_pairs = {}
    for _, row in scored.iterrows():
        pid = str(row.PLAYER_ID) if "PLAYER_ID" in scored else ""
        day = str(row.GAME_DATE.date())
        profile = profiles.get((pid, day), profiles.get(pid))
        predicted = _profile_value(profile, "projected_fp")
        if predicted is None:
            excluded += 1
            continue
        actual_fp.append(float(row.FP))
        predicted_fp.append(float(predicted))
        for stat, value in (_profile_value(profile, "projected_stats") or {}).items():
            if stat in scored.columns:
                pair = stat_pairs.setdefault(stat, ([], []))
                pair[0].append(float(row[stat]))
                pair[1].append(float(value))
    return {
        "samples": len(actual_fp),
        "excluded": excluded,
        "fp": compute_forecast_metrics(actual_fp, predicted_fp),
        "stats": {
            stat: compute_forecast_metrics(actual, predicted)
            for stat, (actual, predicted) in sorted(stat_pairs.items())
        },
    }


def _raw_normal(history, game, remaining, cfg, name):
    """LOCK iff the raw normal tail probability says no later game beats this."""
    dcfg = cfg.get("decision", {})
    recent = last_n_days(history, dcfg.get("recent_days", 14), game.GAME_DATE)
    base = (recent if not recent.empty else history).tail(
        dcfg.get("lookback_games", 10)
    )
    baseline = rolling_baseline(base, dcfg.get("lookback_games", 10), cfg, name, None)
    p_future = probability_future_beats_current(
        float(game.FP), int(remaining), baseline["fp_mean"], baseline["fp_std"]
    )
    p_lock = float(np.clip(1.0 - p_future, 0.0, 1.0))
    return ("LOCK" if p_lock >= 0.5 else "WAIT"), p_lock


def simulate_weekly_lock(
    player_games, weights, cfg, policy="B0", week_start=None, previous_games=None
):
    """Replay one player's week under a lock policy and measure Oracle regret."""
    policy = str(policy).upper()
    if policy not in POLICIES:
        raise ValueError("Unknown policy: " + str(policy))
    scored = add_fantasy_points(
        normalize_stats_for_scoring(player_games), weights
    ).sort_values("GAME_DATE")
    result = {"policy": policy, "status": "no_games", "decisions": []}
    if scored.empty:
        return result
    name = str(scored.PLAYER_NAME.iloc[-1]) if "PLAYER_NAME" in scored else "player"
    pid = str(scored.PLAYER_ID.iloc[-1]) if "PLAYER_ID" in scored else ""
    start, end = get_week_bounds(week_start or scored.GAME_DATE.max())
    week = scored[scored.GAME_DATE.between(start, end)]
    result.update(
        week=[str(start.date()), str(end.date())],
        player=name,
        player_id=pid,
        games=int(len(week)),
    )
    if week.empty:
        return result

    oracle_pos = int(np.argmax(week.FP.to_numpy()))
    oracle = week.iloc[oracle_pos]
    locked_pos = None
    forced = False
    decisions = []
    if policy == "ORACLE":
        locked_pos = oracle_pos
    else:
        for pos, (_, game) in enumerate(week.iterrows()):
            day = game.GAME_DATE
            remaining = len(week) - pos - 1
            entry = {
                "date": str(day.date()),
                "game_id": str(game.GAME_ID) if "GAME_ID" in week else None,
                "fp": float(game.FP),
                "remaining": int(remaining),
            }
            if policy == "ALWAYS_WAIT":
                entry["decision"] = "WAIT"
            elif policy == "THRESHOLD_40":
                entry["decision"] = "LOCK" if game.FP >= 40 else "WAIT"
            elif policy == "RAW_NORMAL":
                history = scored[scored.GAME_DATE <= day]
                entry["decision"], entry["p_lock"] = _raw_normal(
                    history, game, remaining, cfg, name
                )
            else:
                out = per_player_week_decision(
                    name,
                    player_games,
                    weights,
                    cfg,
                    pid,
                    reference=day,
                    remaining_games=remaining,
                    career_prior=None,
                    previous_games=previous_games,
                )
                entry["decision"] = out.get("decision") or "ABSTAIN"
                if out.get("p_lock") is not None:
                    entry["p_lock"] = float(out["p_lock"])
            decisions.append(entry)
            if entry["decision"] == "LOCK":
                locked_pos = pos
                break
        if locked_pos is None:
            locked_pos = len(week) - 1
            forced = True
    locked = week.iloc[locked_pos]
    locked_fp, oracle_fp = float(locked.FP), float(oracle.FP)
    result.update(
        status="resolved",
        locked_fp=locked_fp,
        locked_game_date=str(locked.GAME_DATE.date()),
        locked_game_id=str(locked.get("GAME_ID")),
        locked_index=int(locked_pos),
        oracle_fp=oracle_fp,
        oracle_game_date=str(oracle.GAME_DATE.date()),
        oracle_game_id=str(oracle.get("GAME_ID")),
        best_game_hit=bool(locked_fp == oracle_fp),
        regret=round(oracle_fp - locked_fp, 2),
        efficiency=(
            round(locked_fp / oracle_fp * 100, 1)
            if oracle_fp > 0
            else 100.0 if locked_fp == oracle_fp else 0.0
        ),
        forced_final_lock=forced,
        decisions=decisions,
    )
    return result


def _policy_summary(results):
    resolved = [r for r in results if r["status"] == "resolved"]
    if not resolved:
        return {"player_weeks": 0}
    return {
        "player_weeks": len(resolved),
        "total_fp": round(sum(r["locked_fp"] for r in resolved), 2),
        "oracle_fp": round(sum(r["oracle_fp"] for r in resolved), 2),
        "regret_total": round(sum(r["regret"] for r in resolved), 2),
        "regret_mean": round(np.mean([r["regret"] for r in resolved]), 2),
        "efficiency_mean": round(
            float(np.mean([r["efficiency"] for r in resolved])), 1
        ),
        "best_game_hit_rate": round(
            float(np.mean([r["best_game_hit"] for r in resolved])), 3
        ),
        "forced_final_locks": int(sum(r["forced_final_lock"] for r in resolved)),
        "mean_lock_index": round(
            float(np.mean([r["locked_index"] for r in resolved])), 2
        ),
    }


def evaluate_season_weekly_policy(season, game_store, cfg, weights, policies=None):
    """Simulate every completed player-week of a season across all policies."""
    policies = [str(p).upper() for p in (policies or POLICIES)]
    for policy in policies:
        if policy not in POLICIES:
            raise ValueError("Unknown policy: " + policy)
    games = game_store.read(season) if hasattr(game_store, "read") else game_store
    report = {"season": season, "player_weeks": 0, "policies": {}, "weeks": []}
    if games is None or len(games) == 0:
        report["policies"] = {p: _policy_summary([]) for p in policies}
        return report
    frame = games.copy()
    frame["GAME_DATE"] = pd.to_datetime(frame.GAME_DATE)
    frame["PLAYER_ID"] = frame.PLAYER_ID.astype(str)
    frame["WEEK"] = frame.GAME_DATE.dt.normalize() - pd.to_timedelta(
        frame.GAME_DATE.dt.weekday, unit="D"
    )
    combos = frame[["PLAYER_ID", "WEEK"]].drop_duplicates()
    results = {policy: [] for policy in policies}
    for pid, week_start in sorted(
        combos.itertuples(index=False), key=lambda c: (c[1], c[0])
    ):
        player_games = frame[frame.PLAYER_ID == pid].sort_values("GAME_DATE")
        for policy in policies:
            results[policy].append(
                simulate_weekly_lock(
                    player_games, weights, cfg, policy, week_start=week_start
                )
            )
    report["player_weeks"] = len(results[policies[0]])
    report["policies"] = {
        policy: _policy_summary(results[policy]) for policy in policies
    }
    report["weeks"] = {policy: results[policy] for policy in policies}
    return report


def _print_weekly_table(report):
    header = (
        f"{'policy':<12} {'weeks':>5} {'retained':>9} {'oracle':>9} "
        f"{'regret':>7} {'eff%':>6} {'hit':>6} {'forced':>6}"
    )
    print(header)
    print("-" * len(header))
    for name, s in report["policies"].items():
        if not s.get("player_weeks"):
            print(
                f"{name:<12} {0:>5} {'—':>9} {'—':>9} {'—':>7} {'—':>6} {'—':>6} {'—':>6}"
            )
            continue
        print(
            f"{name:<12} {s['player_weeks']:>5} {s['total_fp']:>9.1f} "
            f"{s['oracle_fp']:>9.1f} {s['regret_total']:>7.1f} "
            f"{s['efficiency_mean']:>6.1f} {s['best_game_hit_rate']:>6.3f} "
            f"{s['forced_final_locks']:>6d}"
        )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Offline evaluation: forecast error and weekly lock regret."
    )
    parser.add_argument("--mode", choices=["weekly", "game"], default="weekly")
    parser.add_argument("--season", default=None)
    parser.add_argument(
        "--db",
        default=None,
        help="SQLite path; default LOCKIN_DB_PATH or data/lockin.sqlite3",
    )
    parser.add_argument("--json", action="store_true", help="print full JSON report")
    args = parser.parse_args(argv)

    from storage import load_cfg

    cfg = load_cfg()
    weights = cfg.get("weights", {})
    season = args.season or _season_for_today()
    if args.mode == "weekly":
        from game_store import GameStore

        report = evaluate_season_weekly_policy(season, GameStore(args.db), cfg, weights)
        if not args.json:
            _print_weekly_table(report)
        else:
            print(json.dumps(report, indent=2, default=str))
    else:
        from forecast_store import ForecastStore

        store = ForecastStore(args.db)
        games = store.read(season)
        profiles = {}
        for day in sorted({str(d.date()) for d in pd.to_datetime(games.GAME_DATE)}):
            for pid, fp in store.read_forecasts(weights, day).items():
                profiles[(str(pid), day)] = fp
        print(
            json.dumps(
                evaluate_game_forecasts(games, profiles, weights),
                indent=2,
                default=str,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
