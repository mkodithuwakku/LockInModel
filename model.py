"""Model utilities for making lock/wait recommendations from fantasy game logs."""

import os
import numpy as np
import pandas as pd
from typing import Optional, Dict, Any
from logger import get_logger

log = get_logger(__name__)

# Toggle ultra-verbose rarity tracing via env var:
#   export TRACE_RARITY=1
TRACE_RARITY = os.getenv("TRACE_RARITY", "0") == "1"

# --- helpers -----------------------------------------------------------------

def _fmt2(x) -> str:
    """Safe 2-decimal formatter for debug logs."""
    try:
        xf = float(x)
        if not np.isfinite(xf):
            return "NA"
        return f"{xf:.2f}"
    except Exception:
        return "NA"

def _safe_mean_std(fp_series: pd.Series, sample_floor_std: float = 6.0):
    """
    Return (mu, sd, n) with a floor for small samples so sd never degenerates.
    For n == 0 -> (nan, nan), for n == 1 -> sd = 0 (later handled), for 2..2 -> floor.
    """
    a = np.asarray(fp_series, dtype=float)
    a = a[np.isfinite(a)]
    n = a.size
    if n == 0:
        return np.nan, np.nan, 0
    mu = float(np.mean(a))
    if n == 1:
        sd = 0.0
    else:
        sd = float(np.std(a, ddof=1))
    # Early-season floor: if <3 games, enforce a minimum sd so probabilities aren’t degenerate
    if n < 3:
        sd = max(sd, sample_floor_std)
    return mu, sd, int(n)

def _weighted_mean_std(values, weights):
    v = np.asarray(values, dtype=float)
    w = np.asarray(weights, dtype=float)
    m = np.isfinite(v) & np.isfinite(w) & (w > 0)
    v, w = v[m], w[m]
    if w.size == 0:
        return float("nan"), float("nan")
    wsum = np.sum(w)
    mu = float(np.sum(w * v) / wsum)
    var = float(np.sum(w * (v - mu) ** 2) / wsum)
    return mu, float(np.sqrt(max(var, 0.0)))


# --- core --------------------------------------------------------------------

def rolling_baseline(
    df: pd.DataFrame,
    lookback_games: int = 10,
    cfg: Optional[Dict[str, Any]] = None,
    player_name: Optional[str] = None,
    career_fp_prior: Optional[float] = None,
) -> dict:
    """
    Baseline with:
      • exponential weighting of recent games (ALWAYS ON),
      • mean shrinkage toward career FP (if provided),
      • SD floor from career FP (or rookie guard=17.5).
    """
    dcfg = (cfg or {}).get("decision", {})
    decay           = float(dcfg.get("decay", 0.92))          # recency strength (0.90–0.96 typical)
    prior_w         = int(dcfg.get("prior_weight_games", 12)) # pseudo-games for prior
    sd_floor_min    = float(dcfg.get("sd_floor_min", 4.0))
    career_scale    = float(dcfg.get("career_guard_scale", 0.6))
    rookie_guard_fp = float(dcfg.get("rookie_guard_fp", 17.5))

    # Per-player overrides (optional)
    if player_name and "player_overrides" in dcfg:
        ovr = dcfg["player_overrides"].get(player_name) or {}
        prior_w      = int(ovr.get("prior_weight_games", prior_w))
        career_scale = float(ovr.get("career_guard_scale", career_scale))
        decay        = float(ovr.get("decay", decay))

    recent = df.tail(lookback_games).copy()
    # Exclude the most recent game from rarity baselines to avoid leakage
    prev = recent.iloc[:-1].copy() if len(recent) > 1 else recent.iloc[0:0].copy()
    n_recent = len(recent)

    # --- ALWAYS WEIGHTED recent mean/std ---
    if n_recent == 0 or "FP" not in recent.columns:
        fp_mean_recent = float("nan")
        fp_std_recent  = float("nan")
    else:
        # most recent row weight=1.0; older rows decay by `decay`
        w = np.array([decay ** (n_recent - 1 - i) for i in range(n_recent)], dtype=float)
        fp_mean_recent, fp_std_recent = _weighted_mean_std(recent["FP"].to_numpy(), w)
        # (if <3 games in window, leave raw std here; guard applied below)

    # --- career prior (mean) ---
    mu_prior = float(career_fp_prior) if career_fp_prior is not None else float("nan")

    # posterior mean via shrinkage
    if np.isfinite(mu_prior) and n_recent > 0 and prior_w > 0:
        mu_post = (n_recent * fp_mean_recent + prior_w * mu_prior) / (n_recent + prior_w)
    elif n_recent > 0:
        mu_post = fp_mean_recent
    else:
        mu_post = mu_prior  # nothing recent → lean on career if available

    # SD floor from career guard (rookies/missing → fixed guard)
    if not np.isfinite(mu_prior) or mu_prior == 0.0:
        guard_fp = rookie_guard_fp
    else:
        guard_fp = max(sd_floor_min, career_scale * mu_prior)

    if not np.isfinite(fp_std_recent) or n_recent < 3:
        sd_post = max(fp_std_recent if np.isfinite(fp_std_recent) else 0.0, guard_fp)
    else:
        sd_post = max(fp_std_recent, 1e-6)

    # Aggregates over all recent (kept for any other uses)
    numeric = recent.select_dtypes(include=["number"])
    stat_means = numeric.mean().to_dict()
    stat_stds  = (numeric.std(ddof=1).fillna(0.0) + 1e-6).to_dict()

    # Rarity baselines: **previous games only** (exclude the current one)
    numeric_prev = prev.select_dtypes(include=["number"])
    stat_means_prev = numeric_prev.mean().to_dict()
    stat_stds_prev = (numeric_prev.std(ddof=1).fillna(0.0) + 1e-6).to_dict()
    # NOTE: With only 1 previous game, std becomes ~1e-6; that makes z-scores large.
    # If you prefer to suppress rarity until >=2–3 prior games, set stds to NaN when len(prev)<3.
    # Example:
    # if len(prev) < 3: stat_stds_prev = {k: float("nan") for k in stat_means_prev}

    log.debug(
        f"recent(mu,sd,n)=({_fmt2(fp_mean_recent)},{_fmt2(fp_std_recent)},{n_recent}) "
        f"career_prior={_fmt2(mu_prior)} guard_fp={_fmt2(guard_fp)} "
        f"post(mu,sd)=({_fmt2(mu_post)},{_fmt2(sd_post)}) decay={decay}"
    )

    return {
        "fp_mean": mu_post,
        "fp_std": sd_post,
        "sample_size": n_recent,
        "_career_fp_prior": mu_prior,
        "_guard_fp": guard_fp,
        "_decay": decay,
        "stat_means": stat_means,  # optional (all recent)
        "stat_stds": stat_stds,  # optional (all recent)
        "rare_means": stat_means_prev,  # use these for rarity
        "rare_stds": stat_stds_prev,  # use these for rarity
        "_recent_excl_last": prev
    }


def rarity_boost(row: pd.Series,
                 stat_means: dict,
                 stat_stds: dict,
                 rare_stats: list,
                 z_threshold: float) -> float:
    if not rare_stats or not stat_means or not stat_stds:
        return 0.0
    zs = []
    for s in rare_stats:
        val = float(row.get(s, 0) or 0)
        mu  = float(stat_means.get(s, np.nan))
        sd  = float(stat_stds.get(s, np.nan))
        # skip when no previous history
        # Skip if we don't have usable prior variance
        if not np.isfinite(mu) or not np.isfinite(sd) or sd <= 0:
            continue
        z = (val - mu) / sd
        if TRACE_RARITY:
            log.debug(f"[rarity] stat={s} val={_fmt2(val)} mu={_fmt2(mu)} sd={_fmt2(sd)} z={_fmt2(z)}")
        if z >= z_threshold:
            zs.append(z)
    if not zs:
        return 0.0
    z_sum = sum(min(3.0, z) for z in zs)
    return float(1.0 - np.exp(-0.5 * z_sum))


def probability_future_beats_current(current_fp: float, remaining_games: int, fp_mean: float, fp_std: float) -> float:
    """
    Approximate P(max of `remaining_games` future games > current_fp) using a Normal model,
    with robust guards for early-season/tiny samples.
    """
    log.debug(f"P(max>c) with c={_fmt2(current_fp)}, n={remaining_games}, mu={_fmt2(fp_mean)}, sd={_fmt2(fp_std)}")

    if remaining_games <= 0:
        return 0.0

    # If we have no usable sd/mean (start of season), assume 50/50 per game
    if not np.isfinite(fp_mean) or not np.isfinite(fp_std):
        p = float(1.0 - (0.5 ** remaining_games))
        log.debug(f"[normal] no-variance fallback → p(max>c)={_fmt2(p)}")
        return p

    # If sd effectively zero, deterministic compare
    if fp_std <= 1e-6:
        p = 1.0 if fp_mean > current_fp else 0.0
        log.debug(f"[normal] sd≈0 fallback → p(max>c)={_fmt2(p)} (mu {('>' if p==1.0 else '<=')} current)")
        return p

    from math import erf, sqrt
    def Phi(x):  # std normal CDF
        return 0.5 * (1.0 + erf(x / sqrt(2.0)))

    z = (current_fp - fp_mean) / fp_std
    p_le_c = Phi(z)
    p_all_le_c = (p_le_c) ** remaining_games
    p = 1.0 - p_all_le_c
    log.debug(f"[normal] z={_fmt2(z)} Phi(z)={_fmt2(p_le_c)} n={remaining_games} all<=c={_fmt2(p_all_le_c)} p(max>c)={_fmt2(p)}")
    return float(np.clip(p, 0.0, 1.0))

def lock_recommendation(current_row: pd.Series,
                        remaining_games: int,
                        baseline: dict,
                        cfg: dict) -> dict:
    """Combine signals into a final lock/wait recommendation, with early-season guards."""
    log.debug(f"Lock rec for FP={_fmt2(current_row.get('FP', np.nan))} with remaining={remaining_games}")

    fp_mean = baseline.get("fp_mean", np.nan)
    fp_std  = baseline.get("fp_std",  np.nan)
    sample  = int(baseline.get("sample_size") or 0)

    # Base probability (future beats current)
    p_future_beats = probability_future_beats_current(
        current_fp=float(current_row.get("FP", 0.0)),
        remaining_games=int(remaining_games),
        fp_mean=float(fp_mean) if fp_mean is not None else np.nan,
        fp_std=float(fp_std)  if fp_std  is not None else np.nan
    )
    p_lock = 1.0 - p_future_beats

    # Rarity
    dcfg = cfg.get("decision", {})
    base_rare = dcfg.get("rare_stats", ["BLK", "STL"])
    derived_rare = ["DD", "TD", "PTS50", "PTS40"]  # always include by default
    rare_stats = list(dict.fromkeys(list(base_rare) + derived_rare))
    zthr = float(dcfg.get("rare_z_threshold", 1.75))
    # Use baselines that EXCLUDE the current game
    rare_means = baseline.get("rare_means", {})
    rare_stds = baseline.get("rare_stds", {})
    rarity = rarity_boost(current_row, rare_means, rare_stds, rare_stats, zthr)
    p_lock += rarity * float(dcfg.get("lock_bias_if_rare", 0.15))

    # Early-season tiny sample → nudge toward WAIT unless last game is truly special
    if sample < 3 and remaining_games > 0:
        p_lock -= 0.10

    # More remaining games → slight wait bias
    if remaining_games >= 2:
        p_lock -= float(dcfg.get("min_remaining_games_bias", 0.05))

    # Conservative mode knob
    if dcfg.get("conservative_mode", False):
        p_lock += 0.05

    p_lock = float(np.clip(p_lock, 0.0, 1.0))
    decision = "LOCK" if p_lock >= 0.5 else "WAIT"

    log.debug(f"p_lock={_fmt2(p_lock)}, rarity={_fmt2(rarity)}, decision={decision}")

    return {
        "p_lock": p_lock,
        "p_wait": float(1.0 - p_lock),
        "decision": decision,
        "rarity_score": float(rarity)
    }
