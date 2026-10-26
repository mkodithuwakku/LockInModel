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
from season_history import blend_seasons

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
    previous_games=None,
    future_mus=None,
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
        blend = blend_seasons(
            logs, previous_games, weights, cfg["decision"]["lookback_games"], reference
        )
        if blend:
            history, current_count, prior_count = blend
            base = add_fantasy_points(history, weights)
            # These prior games are already real rows in the window; do not
            # count them again as a pseudo-game mean-shrinkage prior.
            career_prior = None
            result.update(
                baseline_source="blended_seasons",
                baseline_current_season_games=current_count,
                baseline_prior_season_games=prior_count,
                baseline_window_games=cfg["decision"]["lookback_games"],
            )
        week = filter_week_games(logs, start, end)
        if week.empty:
            baseline = rolling_baseline(
                base,
                cfg["decision"]["lookback_games"],
                cfg,
                player_name,
                None if career_prior is UNSET else career_prior,
            )
            result.update(
                fp_mean_recent=float(baseline["fp_mean"]),
                fp_std_recent=float(baseline["fp_std"]),
                sample_size=len(base),
            )
            if isinstance(remaining_games, (int, np.integer)) and remaining_games >= 0:
                result["remaining_games_est"] = int(remaining_games)
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
        rec = lock_recommendation(
            last, remaining_games, baseline, cfg, future_mus=future_mus
        )
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


def _norm_cdf(x: float) -> float:
    from math import erf, sqrt

    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def _contender_future_mus(row: dict) -> list:
    """Per-game projected means for a roster player's remaining week games."""
    rem = row.get("remaining_games_est")
    if not isinstance(rem, (int, np.integer)) or rem <= 0:
        return []
    last_date = str(row.get("last_game_date") or "")
    fallback_mu = (
        (row.get("projection") or {}).get("projected_fp")
        if isinstance(row.get("projection"), dict)
        else None
    )
    if fallback_mu is None or not np.isfinite(fallback_mu):
        fallback_mu = row.get("fp_mean_recent")
    if fallback_mu is None or not np.isfinite(fallback_mu):
        return []
    fallback_mu = float(fallback_mu)

    future_games = sorted(
        (
            g
            for g in (row.get("week_games") or [])
            if g.get("status") in ("pre_game", "scheduled", "in_game", "in_progress")
            and (not last_date or str(g.get("date") or "") > last_date)
        ),
        key=lambda g: str(g.get("date") or ""),
    )
    mus = []
    for g in future_games[: int(rem)]:
        val = g.get("proj_fp")
        mus.append(
            float(val)
            if isinstance(val, (int, float)) and np.isfinite(val)
            else fallback_mu
        )
    if len(mus) < int(rem):
        mus.extend([fallback_mu] * (int(rem) - len(mus)))
    return mus


def _prob_contender_le(target_fp: float, current_fp, future_mus: list, sigma) -> float:
    """P(contender's best weekly score <= target_fp)."""
    if (
        current_fp is not None
        and np.isfinite(current_fp)
        and float(current_fp) > target_fp
    ):
        return 0.0
    if not future_mus:
        return 1.0
    sd = max(float(sigma) if sigma is not None and np.isfinite(sigma) else 4.0, 4.0)
    p = 1.0
    for mu in future_mus:
        p *= _norm_cdf((target_fp - float(mu)) / sd)
    return float(np.clip(p, 0.0, 1.0))


def _expected_contender_max(current_fp, future_mus: list, sigma) -> float:
    """E[max(current_fp, X_1, ..., X_k)] via deterministic 1D quadrature."""
    has_curr = current_fp is not None and np.isfinite(current_fp)
    c_val = float(current_fp) if has_curr else float("-inf")
    if not future_mus:
        return c_val
    sd = max(float(sigma) if sigma is not None and np.isfinite(sigma) else 4.0, 4.0)
    lo = min([m - 5.0 * sd for m in future_mus] + ([c_val] if has_curr else []))
    hi = max([m + 5.0 * sd for m in future_mus] + ([c_val] if has_curr else []))
    steps = 64
    start_x = max(lo, c_val) if has_curr else lo
    if start_x >= hi:
        return c_val
    dx = (hi - start_x) / steps
    integral = 0.0
    for step in range(steps):
        x = start_x + (step + 0.5) * dx
        cdf = 1.0
        for mu in future_mus:
            cdf *= _norm_cdf((x - float(mu)) / sd)
        integral += (1.0 - cdf) * dx
    return float(start_x + integral)


def _first_open_slot(row, slots, pinned, prefer=None):
    from lineup import eligible

    if prefer in slots:
        hit = next(
            (i for i, s in enumerate(slots) if s == prefer and i not in pinned), None
        )
        if hit is not None:
            return hit
    return next(
        (
            i
            for i, s in enumerate(slots)
            if i not in pinned and eligible(row.get("positions"), s)
        ),
        None,
    )


def _roster_reason(row_i, challenger, challenger_profile, p_le, slot, decision):
    """Modal-only slot-contention phrasing; solo reason stands otherwise."""
    c_i = float(row_i["last_game_fp"])
    mu_i = row_i.get("fp_mean_recent")
    rem = row_i.get("remaining_games_est") or 0
    base_txt = (
        f" versus baseline {float(mu_i):.1f}"
        if isinstance(mu_i, (int, float)) and np.isfinite(mu_i)
        else ""
    )
    if decision == "WAIT" and challenger is not None and p_le < 0.65:
        name = challenger.get("player") or "a roster contender"
        curr_j = challenger_profile.get("current_fp")
        if curr_j is not None and curr_j > c_i and not challenger_profile["future_mus"]:
            return (
                f"Latest score {c_i:.1f} FP trails {name} ({float(curr_j):.1f} "
                f"FP); locking now would leave them without a lineup slot."
            )
        rem_j = len(challenger_profile["future_mus"])
        rem_txt = f"{rem} remaining" if rem else "no remaining games"
        return (
            f"Latest score {c_i:.1f} FP{base_txt} ({rem_txt}); wait — locking "
            f"now would leave {name} ({challenger_profile['expected_max']:.1f} "
            f"proj FP, {rem_j} remaining) without a lineup slot."
        )
    if decision == "LOCK" and challenger is not None:
        name = challenger.get("player") or "a roster contender"
        if rem:
            return (
                f"Latest score {c_i:.1f} FP{base_txt} ({rem} remaining) "
                f"clears lineup contender {name}."
            )
        return (
            f"No further team games in the verified week; {c_i:.1f} FP "
            f"clears lineup contender {name}."
        )
    return row_i.get("reason")


def apply_roster_lock_context(team, rows, locks=None):
    """Stage 2: adjust solo Lock/Wait rows for open-slot roster contention.

    Stage 1 (``per_player_week_decision``) compares a score only to the same
    player's remaining games. Here every decided row competes for the league's
    unpinned active slots: a Hungarian assignment over teammates' expected
    weekly ceilings finds the marginal displaced contender ``j*``, and the solo
    lock probability is weighted by ``P(M_j* <= c_i)``. Reasoning lands only in
    ``row["reason"]`` (rendered inside the player modal); quick-view cards and
    lineup behaviour are unchanged. Rows are mutated in place; idempotent.
    """
    from lineup import (
        OUT,
        active_slots,
        eligible,
        lock_match,
        optimal_assignment,
        _pin_index,
    )

    slots = active_slots(team or {})
    if not slots:
        return rows

    # 1. Resolve pinned slots from lock records, banked scores, or marked rows.
    records = []
    if isinstance(locks, dict):
        for key, record in locks.items():
            if isinstance(record, dict):
                rec = dict(record)
                rec.setdefault("player_name", rec.get("player_name") or key)
                records.append(rec)
    elif locks:
        records = [r for r in locks if isinstance(r, dict)]
    pinned, claimed = {}, set()
    for record in records:
        hit = next(
            (
                i
                for i, row in enumerate(rows)
                if i not in claimed and lock_match(row, record)
            ),
            None,
        )
        if hit is None:
            continue
        index = _pin_index(rows[hit], record, slots, pinned)
        if index is None:
            index = _first_open_slot(rows[hit], slots, pinned)
        if index is not None:
            pinned[index] = hit
            claimed.add(hit)
    for i, row in enumerate(rows):
        if i in claimed:
            continue
        if (
            row.get("is_locked")
            or row.get("banked")
            or str(row.get("status") or "") == "BANKED"
        ):
            index = _first_open_slot(row, slots, pinned, prefer=row.get("roster_slot"))
            if index is not None:
                pinned[index] = i
                claimed.add(i)
    open_slots = [s for i, s in enumerate(slots) if i not in pinned]

    # 2. Expected weekly ceiling for every unpinned, active, healthy teammate.
    pinned_rows = set(pinned.values())
    profiles = {}
    for j, row in enumerate(rows):
        if j in pinned_rows or row.get("roster_slot") in {"IR", "TAXI"}:
            continue
        if str(row.get("injury_status") or "").upper().replace(" ", "_") in OUT:
            continue
        mus = _contender_future_mus(row)
        curr = (
            row.get("last_game_fp") if row.get("decision") in ("LOCK", "WAIT") else None
        )
        if curr is not None and not np.isfinite(curr):
            curr = None
        sigma = row.get("fp_std_recent") or 4.0
        profiles[j] = {
            "future_mus": mus,
            "current_fp": curr,
            "sigma": sigma,
            "expected_max": _expected_contender_max(curr, mus, sigma),
        }

    # 3. Marginal displaced contender per candidate via Hungarian assignment.
    for i, row_i in enumerate(rows):
        if i in pinned_rows or row_i.get("decision") not in ("LOCK", "WAIT"):
            continue
        if row_i.get("is_locked") or row_i.get("banked"):
            continue
        c_i = row_i.get("last_game_fp")
        if c_i is None or not np.isfinite(c_i):
            continue
        c_i = float(c_i)
        if not isinstance(row_i.get("p_lock_solo"), (int, float)) or not np.isfinite(
            row_i["p_lock_solo"]
        ):
            row_i["p_lock_solo"] = row_i.get("p_lock")
            row_i["decision_solo"] = row_i.get("decision")
        p_solo = row_i["p_lock_solo"]
        p_solo = (
            float(p_solo)
            if isinstance(p_solo, (int, float)) and np.isfinite(p_solo)
            else (1.0 if row_i["decision"] == "LOCK" else 0.0)
        )

        slot_names = [
            s for s in dict.fromkeys(open_slots) if eligible(row_i.get("positions"), s)
        ]
        if not slot_names:
            row_i.update(
                p_lock=0.0,
                p_wait=1.0,
                decision="WAIT",
                status="WAIT",
                reason="All eligible lineup slots ({}) are already pinned this week.".format(
                    "/".join(row_i.get("positions") or ["slot"])
                ),
            )
            continue

        others = [
            {
                "index": j,
                "positions": rows[j].get("positions") or [],
                "projected_fp": max(0.0, profiles[j]["expected_max"]),
            }
            for j in profiles
            if j != i and profiles[j]["expected_max"] > float("-inf")
        ]
        base_assign = optimal_assignment(open_slots, others)
        base_chosen = {others[k]["index"] for k in base_assign if k is not None}
        best_slot, best_total, best_chosen = None, float("-inf"), set()
        for s in slot_names:
            reduced = list(open_slots)
            reduced.remove(s)
            assign = optimal_assignment(reduced, others)
            total = sum(others[k]["projected_fp"] for k in assign if k is not None)
            if total > best_total:
                best_total, best_slot, best_chosen = (
                    total,
                    s,
                    {others[k]["index"] for k in assign if k is not None},
                )
        displaced = base_chosen - best_chosen
        j_star = (
            max(displaced, key=lambda j: profiles[j]["expected_max"])
            if displaced
            else None
        )
        p_le = (
            _prob_contender_le(
                c_i,
                profiles[j_star]["current_fp"],
                profiles[j_star]["future_mus"],
                profiles[j_star]["sigma"],
            )
            if j_star is not None
            else 1.0
        )
        p_team = float(np.clip(p_solo * p_le, 0.0, 1.0))
        decision = "LOCK" if p_team >= 0.5 else "WAIT"
        row_i.update(
            p_lock=p_team,
            p_wait=float(1.0 - p_team),
            decision=decision,
            status=decision,
        )
        row_i["reason"] = _roster_reason(
            row_i,
            rows[j_star] if j_star is not None else None,
            profiles[j_star] if j_star is not None else None,
            p_le,
            best_slot,
            decision,
        )
    return rows
