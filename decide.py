"""Weekly decisions from explicit observations and schedule evidence."""

import datetime as dt
import numpy as np
import pandas as pd
from fetch_data import (
    get_week_bounds,
    filter_week_games,
    last_n_days,
    normalize_stats_for_scoring,
    compute_career_fp,
    estimate_remaining_games_this_week,
)
from scoring import add_fantasy_points
from model import rolling_baseline, lock_recommendation
from transport import DataUnavailable

UNSET = object()


def per_player_week_decision(
    player_name,
    raw_logs,
    weights,
    cfg,
    player_id,
    reference=None,
    remaining_games=UNSET,
    career_prior=UNSET,
):
    reference = reference or dt.date.today()
    start, end = get_week_bounds(reference)
    result = {
        "player": player_name,
        "player_id": str(player_id),
        "week": [str(start.date()), str(end.date())],
        "warnings": [],
    }

    def unavailable(status, note):
        result.update(status=status, note=note, decision=None, p_lock=None, p_wait=None)
        return result

    if raw_logs is None:
        return unavailable(
            "DATA_UNAVAILABLE", "Game logs unavailable. No recommendation issued."
        )
    if raw_logs.empty:
        return unavailable("NO_HISTORY", "No observed game history.")
    try:
        logs = add_fantasy_points(normalize_stats_for_scoring(raw_logs), weights)
        logs = last_n_days(logs, 3650, reference)
        result["history"] = [
            {
                "date": str(r.GAME_DATE.date()),
                "fp": float(r.FP),
                "minutes": float(r.MIN) if "MIN" in logs else None,
                "pts": float(r.PTS),
                "reb": float(r.REB),
                "ast": float(r.AST),
                "stl": float(r.STL),
                "blk": float(r.BLK),
                "tov": float(r.TOV),
            }
            for _, r in logs.tail(25).iterrows()
        ]
        if logs.empty:
            return unavailable(
                "NO_HISTORY", "No games available by this decision date."
            )
        result["nba_team"] = str(logs.iloc[-1].get("TEAM_ABBREVIATION", ""))
        recent = last_n_days(logs, cfg["decision"]["recent_days"], reference)
        base = (recent if not recent.empty else logs).tail(
            cfg["decision"]["lookback_games"]
        )
        week = filter_week_games(logs, start, end)
        if week.empty:
            return unavailable("NO_GAME", "No completed game this week.")
        last = week.iloc[-1]
        result.update(
            last_game_date=str(last.GAME_DATE.date()), last_game_fp=float(last.FP)
        )
        if remaining_games is UNSET:
            try:
                remaining_games = estimate_remaining_games_this_week(
                    player_id, last.GAME_DATE, end
                )
            except DataUnavailable as exc:
                return unavailable("SCHEDULE_UNAVAILABLE", str(exc))
        if (
            remaining_games is None
            or not isinstance(remaining_games, (int, np.integer))
            or remaining_games < 0
        ):
            return unavailable(
                "SCHEDULE_UNAVAILABLE",
                "Schedule unavailable. No lock recommendation can be made.",
            )
        if career_prior is UNSET:
            try:
                career_prior = compute_career_fp(player_id, weights)
            except DataUnavailable:
                career_prior = None
                result["warnings"].append(
                    "Career prior unavailable; using observed recent form with a variance guard."
                )
        baseline = rolling_baseline(
            base, cfg["decision"]["lookback_games"], cfg, player_name, career_prior
        )
        rec = lock_recommendation(last, remaining_games, baseline, cfg)
        if not np.isfinite(rec["p_lock"]):
            return unavailable("DATA_UNAVAILABLE", "Model inputs are not finite.")
        result.update(
            rec,
            status=rec["decision"],
            remaining_games_est=int(remaining_games),
            fp_mean_recent=float(baseline["fp_mean"]),
            fp_std_recent=float(baseline["fp_std"]),
            sample_size=len(base),
        )
        if len(base) < 3:
            result["warnings"].append(
                "Limited history: fewer than three observed games."
            )
        result["reason"] = (
            "No further team games in the verified week."
            if remaining_games == 0
            else f"Latest score {last.FP:.1f} FP versus baseline {baseline['fp_mean']:.1f}; {remaining_games} remaining opportunities."
        )
        return result
    except (DataUnavailable, ValueError, TypeError, KeyError) as exc:
        return unavailable("DATA_UNAVAILABLE", str(exc))
