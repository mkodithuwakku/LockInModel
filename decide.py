# decide.py

"""Decision helpers for weekly lock-in recommendations."""
import os
import json
import numpy as np
import pandas as pd

from logger import get_logger
log = get_logger(__name__)

from fetch_data import (
    get_week_bounds,
    filter_week_games,
    last_n_days,
    normalize_stats_for_scoring,
    compute_career_fp,                      # NEW
    estimate_remaining_games_this_week,     # NEW
)
from scoring import add_fantasy_points
from model import rolling_baseline, lock_recommendation

def _fmt2(x) -> str:
    try:
        xf = float(x)
        if not np.isfinite(xf):
            return "NA"
        return f"{xf:.2f}"
    except Exception:
        return "NA"

def per_player_week_decision(
    player_name: str,
    raw_logs: pd.DataFrame,
    weights: dict,
    cfg: dict,
    player_id: int,                         # NEW: we need pid for career FP + schedule
) -> dict:
    """Produce a weekly lock/wait recommendation for a single player."""
    log.info(f"== Evaluating {player_name} ==")

    if raw_logs is None or raw_logs.empty:
        return {"player": player_name, "note": "No recent logs", "week": None}

    # Normalize + add FP
    logs = normalize_stats_for_scoring(raw_logs)
    logs = add_fantasy_points(logs, weights)

    # ---- TRACE: overall recent summary ----
    try:
        _fp_desc = logs["FP"].describe().to_dict()
        log.debug(
            f"[{player_name}] FP describe: "
            f"count={int(_fp_desc.get('count',0))}, "
            f"mean={_fmt2(_fp_desc.get('mean'))}, "
            f"std={_fmt2(_fp_desc.get('std'))} "
            f"min={_fmt2(_fp_desc.get('min'))}, "
            f"25%={_fmt2(_fp_desc.get('25%'))}, "
            f"50%={_fmt2(_fp_desc.get('50%'))}, "
            f"75%={_fmt2(_fp_desc.get('75%'))}, "
            f"max={_fmt2(_fp_desc.get('max'))}"
        )
    except Exception:
        log.debug(f"[{player_name}] FP describe not available")

    # Week isolation
    week_start, week_end = get_week_bounds()
    week_logs = filter_week_games(logs, week_start, week_end)
    log.debug(f"[{player_name}] Week range: {week_start.date()}..{week_end.date()} | week_games={len(week_logs)}")
    if not week_logs.empty:
        _dates = sorted({str(pd.to_datetime(d).date()) for d in week_logs["GAME_DATE"]})
        log.debug(f"[{player_name}] Week game dates: {', '.join(_dates)}")

    if week_logs.empty:
        return {
            "player": player_name,
            "note": "No games yet this week",
            "week": (str(week_start.date()), str(week_end.date()))
        }

    # Determine last played game this week
    last_game = week_logs.sort_values("GAME_DATE").iloc[-1]

    # --- NEW: estimate *future* games this week via PlayerNextNGames
    remaining_games = estimate_remaining_games_this_week(
        player_id=player_id,
        last_game_date=pd.to_datetime(last_game["GAME_DATE"]),
        week_end=week_end,
        lookahead=int(cfg["decision"].get("schedule_lookahead", 30)),
    )
    log.debug(f"[{player_name}] remaining_games (from schedule) = {remaining_games}")

    # Baseline on recent form (use both lookback N games and recent_days)
    lb = int(cfg["decision"]["lookback_games"])
    recent_days = int(cfg["decision"]["recent_days"])
    recent = last_n_days(logs, recent_days)
    base_df = recent.tail(lb) if not recent.empty else logs.tail(lb)
    log.debug(
        f"[{player_name}] Baseline window: rows={len(base_df)} "
        f"(recent_days={recent_days}, lookback_games={lb}) "
        f"date_span={str(base_df['GAME_DATE'].min().date()) if not base_df.empty else 'NA'}.."
        f"{str(base_df['GAME_DATE'].max().date()) if not base_df.empty else 'NA'}"
    )

    # --- NEW: career per-game FP prior (used by early-season guard/shrinkage)
    career_fp_prior = compute_career_fp(player_id, weights)
    log.debug(f"[{player_name}] career_fp_prior={_fmt2(career_fp_prior)}")

    # Build baseline and recommendation (now passing career prior)
    baseline = rolling_baseline(
        base_df,
        lookback_games=lb,
        cfg=cfg,
        player_name=player_name,
        career_fp_prior=career_fp_prior,     # NEW
    )
    rec = lock_recommendation(last_game, remaining_games, baseline, cfg)

    # Baseline internals
    mu_post = baseline.get("fp_mean")
    sd_post = baseline.get("fp_std")
    guard   = baseline.get("_guard_fp")
    decay   = baseline.get("_decay")
    mu_prior= baseline.get("_career_fp_prior")
    log.debug(
        f"[{player_name}] Baseline: mu_post={_fmt2(mu_post)}, "
        f"sd_post={_fmt2(sd_post)}, career_prior={_fmt2(mu_prior)}, "
        f"guard={_fmt2(guard)}, decay={decay if decay is not None else 'NA'}"
    )

    # Final recommendation math
    log.debug(
        f"[{player_name}] Decision: {rec['decision']} "
        f"(p_lock={_fmt2(rec['p_lock'])}, p_wait={_fmt2(rec['p_wait'])}, rarity={_fmt2(rec['rarity_score'])})"
    )
    log.info(
        f"{player_name}: decision={rec['decision']} (p_lock={_fmt2(rec['p_lock'])}, rarity={_fmt2(rec['rarity_score'])})"
    )

    return {
        "player": player_name,
        "week": (str(week_start.date()), str(week_end.date())),
        "last_game_date": str(pd.to_datetime(last_game["GAME_DATE"]).date()),
        "last_game_fp": float(last_game.get("FP", float("nan"))),
        "remaining_games_est": int(remaining_games),
        "fp_mean_recent": float(baseline.get("fp_mean")) if pd.notna(baseline.get("fp_mean")) else None,
        "fp_std_recent": float(baseline.get("fp_std")) if pd.notna(baseline.get("fp_std")) else None,
        "rarity_score": float(rec.get("rarity_score", 0.0)),
        "p_lock": float(rec.get("p_lock", 0.0)),
        "p_wait": float(rec.get("p_wait", 0.0)),
        "decision": rec.get("decision", "WAIT"),
    }
