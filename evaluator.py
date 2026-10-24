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
import itertools
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

POLICIES = (
    "B0",
    "RAW_NORMAL",
    "ALWAYS_WAIT",
    "THRESHOLD_40",
    "CHALLENGER_C1",
    "ORACLE",
)

# Slot-constrained team replays: SOLO_* policies decide per player like their
# weekly counterparts, ROSTER_* add the Stage 2 open-slot contention pass, and
# TEAM_ORACLE optimally assigns each roster player's weekly best into slots.
TEAM_POLICIES = (
    "SOLO_B0",
    "ROSTER_B0",
    "SOLO_C1",
    "ROSTER_C1",
    "ALWAYS_WAIT",
    "THRESHOLD_40",
    "TEAM_ORACLE",
)

DEFAULT_TEAM_SLOTS = ["PG", "SG", "G", "SF", "PF", "F", "C", "UTIL", "UTIL", "UTIL"]


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


def _c1_lock_prob(current_fp, predicted_fps, sigma):
    """P(all remaining games stay at or below current) under independent normals."""
    from math import erf, sqrt

    preds = [float(p) for p in predicted_fps if np.isfinite(p)]
    if not preds:
        return 1.0
    if not np.isfinite(sigma) or sigma <= 1e-6:
        return 1.0 if all(p <= current_fp for p in preds) else 0.0
    p_lock = 1.0
    for mu in preds:
        p_lock *= 0.5 * (1.0 + erf((current_fp - mu) / (sigma * sqrt(2.0))))
    return float(np.clip(p_lock, 0.0, 1.0))


def _challenger_c1(context, targets, cutoff, current_fp, weights):
    """C1: opponent-aware Ridge projections for each remaining game."""
    if targets is None or len(targets) == 0:
        return "LOCK", 1.0
    model = (context or {}).get("model")
    builder = (context or {}).get("builder")
    if model is None or builder is None or getattr(model, "n_train", 0) < 100:
        return "ABSTAIN", None
    features = builder.features_for(targets, cutoff=cutoff)
    preds = np.asarray(model.predict_fp(features, weights), dtype=float)
    p_lock = _c1_lock_prob(current_fp, preds, model.fp_resid_std)
    return ("LOCK" if p_lock >= 0.5 else "WAIT"), p_lock


def simulate_weekly_lock(
    player_games,
    weights,
    cfg,
    policy="B0",
    week_start=None,
    previous_games=None,
    context=None,
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
            elif policy == "CHALLENGER_C1":
                targets = week.iloc[pos + 1 :]
                cutoff = day + pd.Timedelta(days=1)
                entry["decision"], entry["p_lock"] = _challenger_c1(
                    context, targets, cutoff, float(game.FP), weights
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


def evaluate_season_weekly_policy(
    season,
    game_store,
    cfg,
    weights,
    policies=None,
    history=None,
    positions=None,
    limit=None,
):
    """Simulate every completed player-week of a season across all policies.

    ``history`` may supply extra game rows (e.g. a prior season) used for player
    form, opponent context and C1 training without adding evaluated weeks.
    ``positions`` maps player_id to a primary-position label for C1 features.
    ``limit`` caps the number of evaluated player-weeks (chronological).
    """
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
    prior = None
    if history is not None and len(history):
        prior = history.copy()
        prior["GAME_DATE"] = pd.to_datetime(prior.GAME_DATE)
        prior["PLAYER_ID"] = prior.PLAYER_ID.astype(str)
        prior = prior[prior.GAME_DATE < frame.GAME_DATE.min()]
        if prior.empty:
            prior = None
    c1 = None
    if "CHALLENGER_C1" in policies:
        from features import FeatureBuilder
        from model_ml import ComponentRidge, model_settings

        settings = model_settings(cfg)
        all_games = (
            pd.concat([prior, frame], ignore_index=True) if prior is not None else frame
        )
        builder = FeatureBuilder(
            all_games,
            positions=positions,
            window=settings["feature_window"],
            decay=settings["player_decay"],
            lookback=settings["player_lookback"],
        )
        matrix = builder.training_matrix()
        c1 = {"builder": builder, "matrix": matrix, "models": {}}

        def weekly_model(week_start):
            key = str(pd.Timestamp(week_start).date())
            if key not in c1["models"]:
                train = c1["matrix"][c1["matrix"].GAME_DATE < week_start]
                c1["models"][key] = ComponentRidge(lam=settings["ridge_lambda"]).fit(
                    train, weights
                )
            return c1["models"][key]

        c1["weekly_model"] = weekly_model
    combos = sorted(
        frame[["PLAYER_ID", "WEEK"]].drop_duplicates().itertuples(index=False),
        key=lambda c: (c[1], c[0]),
    )
    if limit:
        combos = combos[:limit]
    results = {policy: [] for policy in policies}
    for pid, week_start in combos:
        player_games = frame[frame.PLAYER_ID == pid].sort_values("GAME_DATE")
        previous_games = None
        if prior is not None:
            prev = prior[prior.PLAYER_ID == pid]
            previous_games = prev if len(prev) else None
        context = (
            {
                "builder": c1["builder"],
                "model": c1["weekly_model"](week_start),
            }
            if c1
            else None
        )
        for policy in policies:
            results[policy].append(
                simulate_weekly_lock(
                    player_games,
                    weights,
                    cfg,
                    policy,
                    week_start=week_start,
                    previous_games=previous_games,
                    context=context,
                )
            )
    report["player_weeks"] = len(results[policies[0]])
    report["policies"] = {
        policy: _policy_summary(results[policy]) for policy in policies
    }
    report["weeks"] = {policy: results[policy] for policy in policies}
    return report


def _team_position_list(positions, pid):
    """A roster player's eligible positions; unknown players flex anywhere."""
    from lineup import POSITIONS

    raw = (positions or {}).get(str(pid))
    if isinstance(raw, str):
        raw = [raw]
    cleaned = [str(p) for p in (raw or []) if str(p) in POSITIONS]
    return cleaned or sorted(POSITIONS)


def _c1_target_mus(context, targets, cutoff, weights):
    """C1 Ridge means for each remaining target game; None when unavailable."""
    if targets is None or len(targets) == 0:
        return []
    model = (context or {}).get("model")
    builder = (context or {}).get("builder")
    if model is None or builder is None or getattr(model, "n_train", 0) < 100:
        return None
    try:
        features = builder.features_for(targets, cutoff=cutoff)
        preds = np.asarray(model.predict_fp(features, weights), dtype=float)
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    return [float(p) if np.isfinite(p) else None for p in preds]


def simulate_team_weekly_locks(
    team_games,
    slots,
    weights,
    cfg,
    policy="ROSTER_B0",
    week_start=None,
    previous_games=None,
    positions=None,
    context=None,
):
    """Replay one roster's week under a slot-constrained team lock policy.

    Sequential policies rebuild every unlocked roster player's decision as of
    each game day (Stage 1 solo logic; ROSTER_* policies then run the Stage 2
    open-slot contention pass across the team). LOCKs pin into open slots in
    (p_lock, fp) order using the same marginal-slot choice as production, and
    leftover slots fill at week end with each unlocked player's final game.
    ``TEAM_ORACLE`` optimally assigns every player's weekly best into slots.
    """
    from decide import (
        _contender_future_mus,
        _expected_contender_max,
        apply_roster_lock_context,
    )
    from lineup import eligible, optimal_assignment

    policy = str(policy).upper()
    if policy not in TEAM_POLICIES:
        raise ValueError("Unknown team policy: " + str(policy))
    result = {"policy": policy, "status": "no_games", "decisions": []}
    if team_games is None or len(team_games) == 0 or not slots:
        return result
    scored = add_fantasy_points(
        normalize_stats_for_scoring(team_games), weights
    ).sort_values("GAME_DATE")
    if scored.empty:
        return result
    scored["GAME_DATE"] = pd.to_datetime(scored.GAME_DATE)
    scored["PLAYER_ID"] = scored.PLAYER_ID.astype(str)
    slots = [str(s) for s in slots]
    start, end = get_week_bounds(week_start or scored.GAME_DATE.max())
    week = scored[scored.GAME_DATE.between(start, end)]
    result.update(
        week=[str(start.date()), str(end.date())],
        slots=list(slots),
        games=int(len(week)),
    )
    if week.empty:
        return result
    names = (
        {
            str(r.PLAYER_ID): str(r.PLAYER_NAME)
            for r in scored[["PLAYER_ID", "PLAYER_NAME"]].drop_duplicates().itertuples()
        }
        if "PLAYER_NAME" in scored
        else {}
    )
    best = week.groupby(week.PLAYER_ID).FP.max()
    oracle_candidates = [
        {
            "index": pid,
            "positions": _team_position_list(positions, pid),
            "projected_fp": float(fp),
        }
        for pid, fp in best.items()
    ]
    oracle_assign = optimal_assignment(slots, oracle_candidates)
    oracle_fp = round(
        sum(
            oracle_candidates[k]["projected_fp"] for k in oracle_assign if k is not None
        ),
        2,
    )
    result["oracle_fp"] = oracle_fp
    if policy == "TEAM_ORACLE":
        result.update(
            status="resolved",
            total_fp=oracle_fp,
            regret=0.0,
            efficiency=100.0,
            locked_count=0,
        )
        return result

    prior = None
    if previous_games is not None and len(previous_games):
        prior = previous_games.copy()
        prior["PLAYER_ID"] = prior.PLAYER_ID.astype(str)
        prior["GAME_DATE"] = pd.to_datetime(prior.GAME_DATE)
    roster_pids = sorted(str(p) for p in week.PLAYER_ID.unique())
    pinned = {}  # slot index -> {"pid", "fp", "date"}
    decisions = []
    for day in sorted(week.GAME_DATE.unique()):
        day = pd.Timestamp(day)
        cutoff = day + pd.Timedelta(days=1)
        played_fp = {
            str(r.PLAYER_ID): float(r.FP)
            for r in week[week.GAME_DATE == day].itertuples()
        }
        pinned_pids = {v["pid"] for v in pinned.values()}
        rows = []
        for pid in roster_pids:
            if pid in pinned_pids:
                continue
            pweek = week[week.PLAYER_ID == pid]
            remaining = int((pweek.GAME_DATE > day).sum())
            future = pweek[pweek.GAME_DATE > day].sort_values("GAME_DATE")
            future_mus, tile_pred = None, {}
            if policy in ("SOLO_C1", "ROSTER_C1") and remaining:
                mus = _c1_target_mus(context, future, cutoff, weights)
                if mus is not None:
                    future_mus = mus
                    tile_pred = {
                        str(g.GAME_DATE.date()): m
                        for (_, g), m in zip(future.iterrows(), mus)
                    }
            prev = None
            if prior is not None:
                prev_g = prior[prior.PLAYER_ID == pid]
                prev = prev_g if len(prev_g) else None
            out = per_player_week_decision(
                names.get(pid, pid),
                scored[scored.PLAYER_ID == pid],
                weights,
                cfg,
                pid,
                reference=day,
                remaining_games=remaining,
                career_prior=None,
                previous_games=prev,
                future_mus=future_mus,
            )
            row = dict(out)
            row.update(
                player=names.get(pid, pid),
                player_id=pid,
                positions=_team_position_list(positions, pid),
                roster_slot="START",
                injury_status=None,
                projection=(
                    {"projected_fp": float(out["fp_mean_recent"])}
                    if np.isfinite(out.get("fp_mean_recent") or np.nan)
                    else None
                ),
                week_games=[
                    {
                        "date": str(g.GAME_DATE.date()),
                        "status": "complete" if g.GAME_DATE <= day else "pre_game",
                        "proj_fp": tile_pred.get(
                            str(g.GAME_DATE.date()), out.get("fp_mean_recent")
                        ),
                    }
                    for _, g in pweek.iterrows()
                ],
            )
            if pid in played_fp:
                if policy == "ALWAYS_WAIT":
                    row.update(decision="WAIT", status="WAIT", p_lock=0.0, p_wait=1.0)
                elif policy == "THRESHOLD_40":
                    lock = played_fp[pid] >= 40
                    row.update(
                        decision="LOCK" if lock else "WAIT",
                        status="LOCK" if lock else "WAIT",
                        p_lock=1.0 if lock else 0.0,
                        p_wait=0.0 if lock else 1.0,
                    )
            rows.append(row)
        if policy in ("ROSTER_B0", "ROSTER_C1"):
            apply_roster_lock_context(
                {"roster_positions": list(slots), "source": "local"},
                rows,
                locks={
                    str(idx): {
                        "player_id": rec["pid"],
                        "player_name": names.get(rec["pid"]),
                        "roster_slot": slots[idx],
                        "slot_index": idx,
                        "locked_fp": rec["fp"],
                        "game_date": rec["date"],
                    }
                    for idx, rec in pinned.items()
                },
            )
        by_pid = {str(r["player_id"]): r for r in rows}
        entry_map = {}
        for pid, fp in sorted(played_fp.items()):
            r = by_pid.get(pid) or {}
            entry = {
                "date": str(day.date()),
                "player": names.get(pid, pid),
                "player_id": pid,
                "fp": fp,
                "decision": r.get("decision") or "ABSTAIN",
            }
            if r.get("p_lock") is not None:
                entry["p_lock"] = float(r["p_lock"])
            decisions.append(entry)
            entry_map[pid] = entry
        lockers = sorted(
            (
                r
                for r in rows
                if str(r["player_id"]) in played_fp and r.get("decision") == "LOCK"
            ),
            key=lambda r: (
                -(r.get("p_lock") or 0.0),
                -(r.get("last_game_fp") or 0.0),
                str(r["player_id"]),
            ),
        )
        for r in lockers:
            pid = str(r["player_id"])
            open_idx = [i for i in range(len(slots)) if i not in pinned]
            open_names = [slots[i] for i in open_idx]
            slot_names = [
                s for s in dict.fromkeys(open_names) if eligible(r["positions"], s)
            ]
            if not slot_names:
                continue
            contenders = []
            for other in rows:
                opid = str(other["player_id"])
                if opid == pid or opid in pinned_pids:
                    continue
                mus = _contender_future_mus(other)
                curr = (
                    other.get("last_game_fp")
                    if other.get("decision") in ("LOCK", "WAIT")
                    else None
                )
                ceiling = _expected_contender_max(
                    curr, mus, other.get("fp_std_recent") or 4.0
                )
                if ceiling > float("-inf"):
                    contenders.append(
                        {
                            "index": opid,
                            "positions": other["positions"],
                            "projected_fp": max(0.0, ceiling),
                        }
                    )
            best_name, best_total = None, float("-inf")
            for s in slot_names:
                reduced = list(open_names)
                reduced.remove(s)
                assign = optimal_assignment(reduced, contenders)
                total = sum(
                    contenders[k]["projected_fp"] for k in assign if k is not None
                )
                if total > best_total:
                    best_total, best_name = total, s
            if best_name is None:
                continue
            idx = next(i for i in open_idx if slots[i] == best_name)
            pinned[idx] = {
                "pid": pid,
                "fp": played_fp[pid],
                "date": str(day.date()),
            }
            pinned_pids.add(pid)
            entry_map[pid]["slot"] = best_name

    open_idx = [i for i in range(len(slots)) if i not in pinned]
    pinned_pids = {v["pid"] for v in pinned.values()}
    fillers = [
        {
            "index": pid,
            "positions": _team_position_list(positions, pid),
            "projected_fp": float(week[week.PLAYER_ID == pid].iloc[-1].FP),
        }
        for pid in roster_pids
        if pid not in pinned_pids
    ]
    fill_assign = optimal_assignment([slots[i] for i in open_idx], fillers)
    fill_fp = sum(fillers[k]["projected_fp"] for k in fill_assign if k is not None)
    total_fp = round(sum(v["fp"] for v in pinned.values()) + fill_fp, 2)
    result.update(
        status="resolved",
        total_fp=total_fp,
        regret=round(oracle_fp - total_fp, 2),
        efficiency=(
            round(total_fp / oracle_fp * 100, 1)
            if oracle_fp > 0
            else 100.0 if total_fp == oracle_fp else 0.0
        ),
        locked_count=len(pinned),
        decisions=decisions,
    )
    return result


def _team_policy_summary(results):
    resolved = [r for r in results if r["status"] == "resolved"]
    if not resolved:
        return {"team_weeks": 0}
    return {
        "team_weeks": len(resolved),
        "total_fp": round(sum(r["total_fp"] for r in resolved), 2),
        "oracle_fp": round(sum(r["oracle_fp"] for r in resolved), 2),
        "regret_total": round(sum(r["regret"] for r in resolved), 2),
        "regret_mean": round(np.mean([r["regret"] for r in resolved]), 2),
        "efficiency_mean": round(
            float(np.mean([r["efficiency"] for r in resolved])), 1
        ),
        "locked_slots": int(sum(r["locked_count"] for r in resolved)),
    }


def _partition_rosters(pids, positions, size):
    """Deal the week's active players into position-balanced rosters."""
    ordered = sorted(
        (str(p) for p in pids),
        key=lambda p: (_team_position_list(positions, p)[0], p),
    )
    count = max(1, -(-len(ordered) // max(int(size), 1)))
    rosters = [[] for _ in range(count)]
    for i, pid in enumerate(ordered):
        rosters[i % count].append(pid)
    return rosters


def _cfg_rosters(cfg, frame):
    """(pids, slots) per configured team when every rostered player is stored."""
    from fetch_data import canonical_name
    from lineup import active_slots

    teams = (cfg or {}).get("teams") or []
    if not teams or "PLAYER_NAME" not in frame:
        return None
    ids = {
        canonical_name(str(r.PLAYER_NAME)): str(r.PLAYER_ID)
        for r in frame[["PLAYER_ID", "PLAYER_NAME"]].drop_duplicates().itertuples()
    }
    rosters = []
    for team in teams:
        players = [str(p) for p in team.get("players") or []]
        if not players:
            return None
        pids = [ids.get(canonical_name(p)) for p in players]
        if any(p is None for p in pids):
            return None
        slots = active_slots(team) or list(DEFAULT_TEAM_SLOTS)
        rosters.append((pids, [str(s) for s in slots]))
    return rosters or None


def evaluate_season_team_weekly_policy(
    season,
    game_store,
    cfg,
    weights,
    policies=None,
    history=None,
    positions=None,
    limit=None,
):
    """Simulate slot-constrained team lock weeks across a season.

    Each week's active players are dealt into deterministic position-balanced
    rosters (or the configured ``cfg['teams']`` rosters with their own slots
    when every listed player resolves in the store), then replayed per policy.
    ``limit`` caps the number of evaluated weeks (chronological).
    """
    policies = [str(p).upper() for p in (policies or TEAM_POLICIES)]
    for policy in policies:
        if policy not in TEAM_POLICIES:
            raise ValueError("Unknown team policy: " + policy)
    games = game_store.read(season) if hasattr(game_store, "read") else game_store
    report = {"season": season, "team_weeks": 0, "policies": {}, "weeks": []}
    if games is None or len(games) == 0:
        report["policies"] = {p: _team_policy_summary([]) for p in policies}
        return report
    frame = games.copy()
    frame["GAME_DATE"] = pd.to_datetime(frame.GAME_DATE)
    frame["PLAYER_ID"] = frame.PLAYER_ID.astype(str)
    frame["WEEK"] = frame.GAME_DATE.dt.normalize() - pd.to_timedelta(
        frame.GAME_DATE.dt.weekday, unit="D"
    )
    prior = None
    if history is not None and len(history):
        prior = history.copy()
        prior["GAME_DATE"] = pd.to_datetime(prior.GAME_DATE)
        prior["PLAYER_ID"] = prior.PLAYER_ID.astype(str)
        prior = prior[prior.GAME_DATE < frame.GAME_DATE.min()]
        if prior.empty:
            prior = None
    c1 = None
    if {"SOLO_C1", "ROSTER_C1"} & set(policies):
        from features import FeatureBuilder
        from model_ml import ComponentRidge, model_settings

        settings = model_settings(cfg)
        all_games = (
            pd.concat([prior, frame], ignore_index=True) if prior is not None else frame
        )
        builder = FeatureBuilder(
            all_games,
            positions=positions,
            window=settings["feature_window"],
            decay=settings["player_decay"],
            lookback=settings["player_lookback"],
        )
        matrix = builder.training_matrix()
        matrix["GAME_DATE"] = pd.to_datetime(matrix.GAME_DATE)
        c1 = {"builder": builder, "matrix": matrix, "models": {}}

        def weekly_model(week_start):
            key = str(pd.Timestamp(week_start).date())
            if key not in c1["models"]:
                train = c1["matrix"][c1["matrix"].GAME_DATE < week_start]
                c1["models"][key] = ComponentRidge(lam=settings["ridge_lambda"]).fit(
                    train, weights
                )
            return c1["models"][key]

        c1["weekly_model"] = weekly_model
    configured = _cfg_rosters(cfg, frame)
    week_starts = sorted(frame.WEEK.unique())
    if limit:
        week_starts = week_starts[:limit]
    results = {policy: [] for policy in policies}
    for ws in week_starts:
        wk = frame[frame.WEEK == ws]
        active = set(wk.PLAYER_ID.unique())
        rosters = configured or [
            (roster, DEFAULT_TEAM_SLOTS)
            for roster in _partition_rosters(
                wk.PLAYER_ID.unique(), positions, len(DEFAULT_TEAM_SLOTS)
            )
        ]
        context = (
            {"builder": c1["builder"], "model": c1["weekly_model"](ws)} if c1 else None
        )
        for roster_pids, slots in rosters:
            roster_pids = [p for p in roster_pids if p in active]
            if not roster_pids:
                continue
            team_games = frame[frame.PLAYER_ID.isin(roster_pids)]
            prev = (
                prior[prior.PLAYER_ID.isin(roster_pids)] if prior is not None else None
            )
            for policy in policies:
                results[policy].append(
                    simulate_team_weekly_locks(
                        team_games,
                        slots,
                        weights,
                        cfg,
                        policy,
                        week_start=ws,
                        previous_games=prev,
                        positions=positions,
                        context=context,
                    )
                )
    report["team_weeks"] = len(results[policies[0]])
    report["policies"] = {
        policy: _team_policy_summary(results[policy]) for policy in policies
    }
    report["weeks"] = {policy: results[policy] for policy in policies}
    return report


def evaluate_game_backtest(
    games, cfg, weights, builder=None, positions=None, limit=None, settings=None
):
    """Walk-forward per-date game forecasts for B0 and CHALLENGER_C1.

    B0 is the production baseline (lineup.project_players) recomputed as a
    black box once per slate date; C1 refits closed-form Ridge components on
    feature rows strictly before each date. Both predict only games actually
    played that date, so errors are paired and no future data leaks.
    """
    from lineup import project_players
    from model_ml import ComponentRidge, model_settings

    if settings is None:
        settings = model_settings(cfg)
    report = {"dates": 0, "models": {}}
    if games is None or len(games) == 0:
        return report
    games = games.copy()
    games["GAME_DATE"] = pd.to_datetime(games.GAME_DATE)
    games["PLAYER_ID"] = games.PLAYER_ID.astype(str)
    games = games.sort_values("GAME_DATE")
    if builder is None:
        from features import FeatureBuilder

        builder = FeatureBuilder(
            games,
            positions=positions,
            window=settings["feature_window"],
            decay=settings["player_decay"],
            lookback=settings["player_lookback"],
        )
    matrix = builder.training_matrix()
    matrix["GAME_DATE"] = pd.to_datetime(matrix.GAME_DATE)
    matrix["PLAYER_ID"] = matrix.PLAYER_ID.astype(str)
    scored = add_fantasy_points(normalize_stats_for_scoring(games), weights)
    dates = sorted(scored.GAME_DATE.unique())
    if limit:
        dates = dates[:limit]
    pairs = {"B0": ([], []), "CHALLENGER_C1": ([], [])}
    paired = []  # (key, actual, b0_pred, c1_pred) for shared-coverage metrics
    stat_pairs = {}
    for date in dates:
        date = pd.Timestamp(date)
        day = scored[scored.GAME_DATE == date]
        baseline = project_players(
            games[games.GAME_DATE < date], None, weights, cfg, date
        )
        train = matrix[matrix.GAME_DATE < date]
        model = ComponentRidge(lam=settings["ridge_lambda"]).fit(train, weights)
        today = matrix[matrix.GAME_DATE == date].reset_index(drop=True)
        c1_fp = model.predict_fp(today, weights).reset_index(drop=True)
        c1_stats = model.predict_components(today)
        c1_by_key = {
            (str(row.PLAYER_ID), str(row.GAME_ID)): i for i, row in today.iterrows()
        }
        for _, game in day.iterrows():
            key = (str(game.PLAYER_ID), str(game.GAME_ID))
            profile = baseline.get(str(game.PLAYER_ID))
            b0_pred = None
            if profile and np.isfinite(profile.get("projected_fp", np.nan)):
                b0_pred = float(profile["projected_fp"])
                pairs["B0"][0].append(float(game.FP))
                pairs["B0"][1].append(b0_pred)
            pos = c1_by_key.get(key)
            if pos is not None:
                c1_pred = float(c1_fp.iloc[pos])
                pairs["CHALLENGER_C1"][0].append(float(game.FP))
                pairs["CHALLENGER_C1"][1].append(c1_pred)
                if b0_pred is not None:
                    paired.append((float(game.FP), b0_pred, c1_pred))
                for stat in c1_stats.columns:
                    if stat in game:
                        pair = stat_pairs.setdefault(stat, ([], []))
                        pair[0].append(float(game[stat]))
                        pair[1].append(float(c1_stats.iloc[pos][stat]))
    report["dates"] = len(dates)
    report["models"] = {
        name: compute_forecast_metrics(actual, predicted)
        for name, (actual, predicted) in pairs.items()
    }
    if paired:
        actual, b0_pred, c1_pred = map(list, zip(*paired))
        report["paired"] = {
            "samples": len(paired),
            "B0": compute_forecast_metrics(actual, b0_pred),
            "CHALLENGER_C1": compute_forecast_metrics(actual, c1_pred),
        }
    report["components"] = {
        stat: compute_forecast_metrics(a, p)
        for stat, (a, p) in sorted(stat_pairs.items())
    }
    return report


DEFAULT_TUNE_GRID = {
    "lam": (1.0, 10.0, 50.0),
    "window": (10, 15, 25),
    "decay": (0.90, 0.92, 0.95),
}


def tune_ridge(games, weights, grid=None, positions=None, limit=None, eval_games=None):
    """Grid-search Ridge/feature knobs by walk-forward game FP error.

    Every (lam, window, decay) combo builds its own feature matrix and refits
    once per slate date on strictly-prior rows — the same pregame contract the
    production overlay obeys — and is ranked by MAE on games actually played.
    ``eval_games`` may restrict scoring to a subset (e.g. the target season
    while ``games`` also supplies prior-season training rows).
    Returns a list of {lam, window, decay, mae, rmse, samples} sorted by MAE.
    """
    from features import FeatureBuilder
    from model_ml import ComponentRidge

    if games is None or len(games) == 0:
        return []
    grid = grid or DEFAULT_TUNE_GRID
    games = games.copy()
    games["GAME_DATE"] = pd.to_datetime(games.GAME_DATE)
    games["PLAYER_ID"] = games.PLAYER_ID.astype(str)
    scored = add_fantasy_points(normalize_stats_for_scoring(games), weights)
    actual = {
        (str(r.PLAYER_ID), str(r.GAME_DATE.date())): float(r.FP)
        for r in scored.itertuples()
    }
    evaluate_on = eval_games if eval_games is not None else games
    dates = sorted(pd.to_datetime(evaluate_on.GAME_DATE).unique())
    if limit:
        dates = dates[:limit]
    results = []
    for lam, window, decay in itertools.product(
        grid["lam"], grid["window"], grid["decay"]
    ):
        builder = FeatureBuilder(games, positions=positions, window=window, decay=decay)
        matrix = builder.training_matrix()
        matrix["GAME_DATE"] = pd.to_datetime(matrix.GAME_DATE)
        matrix["PLAYER_ID"] = matrix.PLAYER_ID.astype(str)
        errors = []
        for date in dates:
            date = pd.Timestamp(date)
            train = matrix[matrix.GAME_DATE < date]
            if len(train) < 50:
                continue
            model = ComponentRidge(lam=lam).fit(train)
            today = matrix[matrix.GAME_DATE == date].reset_index(drop=True)
            preds = model.predict_fp(today, weights).reset_index(drop=True)
            for i, row in today.iterrows():
                obs = actual.get((str(row.PLAYER_ID), str(date.date())))
                if obs is not None and np.isfinite(preds.iloc[i]):
                    errors.append(obs - float(preds.iloc[i]))
        errors = np.asarray(errors, dtype=float)
        results.append(
            {
                "lam": lam,
                "window": window,
                "decay": decay,
                "mae": float(np.abs(errors).mean()) if len(errors) else np.nan,
                "rmse": (float(np.sqrt((errors**2).mean())) if len(errors) else np.nan),
                "samples": int(len(errors)),
            }
        )
    return sorted(results, key=lambda r: (np.isnan(r["mae"]), r["mae"]))


def _print_tune_table(results, limit):
    print(f"ridge tuning grid over {limit or 'all'} slate dates (ranked by MAE)")
    header = f"{'rank':>4} {'lam':>6} {'window':>6} {'decay':>6} {'MAE':>7} {'RMSE':>7} {'n':>7}"
    print(header)
    print("-" * len(header))
    for rank, r in enumerate(results, 1):
        print(
            f"{rank:>4} {r['lam']:>6.1f} {r['window']:>6d} {r['decay']:>6.2f} "
            f"{r['mae']:>7.2f} {r['rmse']:>7.2f} {r['samples']:>7d}"
        )
    if results and np.isfinite(results[0]["mae"]):
        best = results[0]
        print(
            "\nbest config — paste under 'model:' in the effective config"
            " (config.local.yaml when present, else config.yaml):"
        )
        print(
            f"  ridge_lambda: {best['lam']}\n"
            f"  feature_window: {best['window']}\n"
            f"  player_decay: {best['decay']}"
        )


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


def _print_team_weekly_table(report):
    header = (
        f"{'policy':<12} {'weeks':>5} {'retained':>9} {'oracle':>9} "
        f"{'regret':>7} {'eff%':>6} {'slots':>6}"
    )
    print(header)
    print("-" * len(header))
    for name, s in report["policies"].items():
        if not s.get("team_weeks"):
            print(f"{name:<12} {0:>5} {'—':>9} {'—':>9} {'—':>7} {'—':>6} {'—':>6}")
            continue
        print(
            f"{name:<12} {s['team_weeks']:>5} {s['total_fp']:>9.1f} "
            f"{s['oracle_fp']:>9.1f} {s['regret_total']:>7.1f} "
            f"{s['efficiency_mean']:>6.1f} {s['locked_slots']:>6d}"
        )


def _store_seasons(store):
    with store.connect() as db:
        return [
            row[0]
            for row in db.execute(
                "SELECT DISTINCT season FROM fact_game_logs ORDER BY season"
            )
        ]


def _store_positions(store):
    import sqlite3

    try:
        with store.connect() as db:
            rows = db.execute(
                "SELECT player_id, primary_position FROM dim_players"
            ).fetchall()
        return {str(pid): pos for pid, pos in rows if pos}
    except sqlite3.Error:
        return {}


def _print_game_table(report):
    print(f"game forecast backtest over {report['dates']} slate dates")
    header = f"{'model':<14} {'samples':>7} {'MAE':>7} {'RMSE':>7} {'bias':>7} {'r':>6}"
    print(header)
    print("-" * len(header))
    for name, m in report["models"].items():
        if not m.get("samples"):
            print(f"{name:<14} {0:>7} {'—':>7} {'—':>7} {'—':>7} {'—':>6}")
            continue
        print(
            f"{name:<14} {m['samples']:>7} {m['mae']:>7.2f} {m['rmse']:>7.2f} "
            f"{m['bias']:>7.2f} {m['correlation']:>6.3f}"
        )
    paired = report.get("paired")
    if paired:
        print(f"\npaired comparison on {paired['samples']} shared samples:")
        for name in ("B0", "CHALLENGER_C1"):
            m = paired[name]
            print(
                f"{name:<14} {m['samples']:>7} {m['mae']:>7.2f} {m['rmse']:>7.2f} "
                f"{m['bias']:>7.2f} {m['correlation']:>6.3f}"
            )
    if report.get("components"):
        print("\ncomponent MAE (CHALLENGER_C1):")
        for stat, m in report["components"].items():
            print(f"  {stat:<5} MAE {m['mae']:>6.2f}  bias {m['bias']:>6.2f}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Offline evaluation: forecast error and weekly lock regret."
    )
    parser.add_argument(
        "--mode",
        choices=["weekly", "team-weekly", "game", "tune"],
        default="weekly",
    )
    parser.add_argument("--season", default=None)
    parser.add_argument(
        "--db",
        default=None,
        help="SQLite path; default LOCKIN_DB_PATH or data/lockin.sqlite3",
    )
    parser.add_argument(
        "--policies",
        default=None,
        help="comma-separated weekly policies (default: all)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="cap evaluated player-weeks (weekly) or slate dates (game)",
    )
    parser.add_argument("--json", action="store_true", help="print full JSON report")
    args = parser.parse_args(argv)

    from storage import load_cfg
    from game_store import GameStore

    cfg = load_cfg()
    weights = cfg.get("weights", {})
    season = args.season or _season_for_today()
    store = GameStore(args.db)
    seasons = _store_seasons(store)
    positions = _store_positions(store)
    if season not in seasons and seasons:
        season = seasons[-1]
        print(f"note: evaluated season set to {season} (latest in database)")
    history = None
    if len(seasons) > 1:
        history = pd.concat(
            [store.read(s) for s in seasons if s != season], ignore_index=True
        )
    if args.mode == "weekly":
        policies = (
            [p.strip() for p in args.policies.split(",")] if args.policies else None
        )
        report = evaluate_season_weekly_policy(
            season,
            store,
            cfg,
            weights,
            policies=policies,
            history=history,
            positions=positions,
            limit=args.limit,
        )
        if not args.json:
            _print_weekly_table(report)
        else:
            print(json.dumps(report, indent=2, default=str))
    elif args.mode == "team-weekly":
        policies = (
            [p.strip() for p in args.policies.split(",")] if args.policies else None
        )
        report = evaluate_season_team_weekly_policy(
            season,
            store,
            cfg,
            weights,
            policies=policies,
            history=history,
            positions=positions,
            limit=args.limit,
        )
        if not args.json:
            _print_team_weekly_table(report)
        else:
            print(json.dumps(report, indent=2, default=str))
    elif args.mode == "tune":
        games = store.read(season)
        all_games = (
            pd.concat([history, games], ignore_index=True)
            if history is not None
            else games
        )
        results = tune_ridge(
            all_games,
            weights,
            positions=positions,
            limit=args.limit,
            eval_games=games,
        )
        if not args.json:
            _print_tune_table(results, args.limit)
        else:
            print(json.dumps(results, indent=2, default=str))
    else:
        from features import FeatureBuilder
        from model_ml import model_settings

        settings = model_settings(cfg)
        games = store.read(season)
        all_games = (
            pd.concat([history, games], ignore_index=True)
            if history is not None
            else games
        )
        report = evaluate_game_backtest(
            games,
            cfg,
            weights,
            positions=positions,
            builder=FeatureBuilder(
                all_games,
                positions=positions,
                window=settings["feature_window"],
                decay=settings["player_decay"],
                lookback=settings["player_lookback"],
            ),
            limit=args.limit,
            settings=settings,
        )
        from forecast_store import ForecastStore

        fstore = ForecastStore(args.db)
        profiles = {}
        for day in sorted({str(d.date()) for d in pd.to_datetime(games.GAME_DATE)}):
            for pid, fp in fstore.read_forecasts(weights, day).items():
                profiles[(str(pid), day)] = fp
        if profiles:
            report["saved_forecasts"] = evaluate_game_forecasts(
                games, profiles, weights
            )
        if not args.json:
            _print_game_table(report)
        else:
            print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
