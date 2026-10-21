"""Daily pregame projections and exact maximum-weight slot assignment."""

import math

import pandas as pd

from fetch_data import normalize_stats_for_scoring
from model import rolling_baseline
from season_history import blend_seasons
from scoring import add_fantasy_points, effective_weights
from transport import DataUnavailable

POSITIONS = {"PG", "SG", "SF", "PF", "C"}
SLOTS = {
    **{p: {p} for p in POSITIONS},
    "G": {"PG", "SG"},
    "F": {"SF", "PF"},
    "UTIL": POSITIONS,
}
RESERVE = {"BN", "IR", "TAXI"}
OUT = {"OUT", "O", "IR", "INJURED_RESERVE", "SUSPENDED", "SUSP", "INACTIVE"}


def active_slots(team):
    """Never infer an imported league's empty slots from occupied players."""
    positions = team.get("roster_positions")
    if positions is None:
        return (
            None
            if team.get("source") == "sleeper"
            else ["UTIL"] * len(team.get("starters", []))
        )
    return [slot for slot in positions if slot not in RESERVE]


def eligible(positions, slot):
    return slot in SLOTS and (
        slot == "UTIL" or bool(set(positions or []) & SLOTS[slot])
    )


def optimal_assignment(slots, candidates):
    """Rectangular Hungarian assignment, O(slots^2 * (players + slots)).

    Each slot gets a unique player or a zero-point vacancy. Integer cents keep
    displayed projections and the objective consistent; no greedy slot ordering.
    """
    n, count = len(slots), len(candidates)
    if not n:
        return []
    m = count + n
    forbidden = sum(abs(round(p["projected_fp"] * 100)) for p in candidates) + 1
    costs = [
        [
            (
                -round(p["projected_fp"] * 100)
                if eligible(p["positions"], slot)
                else forbidden
            )
            for p in candidates
        ]
        + [0] * n
        for slot in slots
    ]
    u, v, assignment, way = [0] * (n + 1), [0] * (m + 1), [0] * (m + 1), [0] * (m + 1)
    for i in range(1, n + 1):
        assignment[0] = i
        j0 = 0
        minimum, used = [math.inf] * (m + 1), [False] * (m + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = assignment[j0], math.inf, 0
            for j in range(1, m + 1):
                if used[j]:
                    continue
                reduced = costs[i0 - 1][j - 1] - u[i0] - v[j]
                if reduced < minimum[j]:
                    minimum[j], way[j] = reduced, j0
                if minimum[j] < delta:
                    delta, j1 = minimum[j], j
            for j in range(m + 1):
                if used[j]:
                    u[assignment[j]] += delta
                    v[j] -= delta
                else:
                    minimum[j] -= delta
            j0 = j1
            if assignment[j0] == 0:
                break
        while True:
            j1 = way[j0]
            assignment[j0] = assignment[j1]
            j0 = j1
            if j0 == 0:
                break
    result = [None] * n
    for j in range(1, count + 1):
        if assignment[j]:
            result[assignment[j] - 1] = j - 1
    return result


def project_players(games, fallback, weights, cfg, reference):
    """Use only games strictly before the target day, including in night replay."""
    reference = pd.Timestamp(reference)
    profiles = {}
    size = cfg["decision"]["lookback_games"]
    season_start = pd.Timestamp(
        year=reference.year if reference.month >= 10 else reference.year - 1,
        month=10,
        day=1,
    )
    previous = {}
    if fallback is not None and not fallback.empty:
        previous = {
            str(pid): h
            for pid, h in fallback[
                fallback.GAME_DATE < min(reference, season_start)
            ].groupby("PLAYER_ID")
        }
    for source, frame in (("current_season", games), ("prior_season", fallback)):
        if frame is None or frame.empty:
            continue
        frame = frame[frame.GAME_DATE < reference]
        if frame.empty:
            continue
        for pid, history in frame.groupby("PLAYER_ID"):
            pid = str(pid)
            if pid in profiles:
                continue
            profile_source = source
            counts = {}
            if source == "current_season":
                blend = blend_seasons(
                    history, previous.get(pid), weights, size, reference
                )
                if blend:
                    history, current_count, prior_count = blend
                    profile_source = "blended_seasons"
                    counts = {
                        "current_season_games": current_count,
                        "prior_season_games": prior_count,
                        "projection_window_games": size,
                    }
            try:
                scored = add_fantasy_points(
                    normalize_stats_for_scoring(history), weights
                ).sort_values("GAME_DATE")
                recent = (
                    scored
                    if profile_source == "blended_seasons"
                    else scored[
                        scored.GAME_DATE
                        >= reference - pd.Timedelta(days=cfg["decision"]["recent_days"])
                    ]
                )
                window = (recent if not recent.empty else scored).tail(
                    cfg["decision"]["lookback_games"]
                )
                older = (
                    scored.iloc[:0]
                    if profile_source == "blended_seasons"
                    else scored[
                        scored.GAME_DATE
                        < reference - pd.Timedelta(days=cfg["decision"]["recent_days"])
                    ]
                )
                prior = (
                    float(older.FP.mean())
                    if not recent.empty and not older.empty
                    else None
                )
                model = rolling_baseline(
                    window,
                    cfg["decision"]["lookback_games"],
                    cfg,
                    str(history.iloc[-1].PLAYER_NAME),
                    prior,
                )
                value = float(model["fp_mean"])
                if not math.isfinite(value):
                    continue
                # Project box-score components with the same recency/shrinkage weights.
                dcfg = dict(
                    cfg["decision"],
                    **cfg["decision"]
                    .get("player_overrides", {})
                    .get(str(history.iloc[-1].PLAYER_NAME), {})
                )
                decay = dcfg.get("decay", 0.92)
                factors = [decay ** (len(window) - i - 1) for i in range(len(window))]
                stats = {}
                for stat in (
                    "PTS",
                    "REB",
                    "AST",
                    "STL",
                    "BLK",
                    "TOV",
                    "FG3M",
                    "MIN",
                    "FGM",
                    "FGA",
                    "FTM",
                    "FTA",
                    "OREB",
                    "DREB",
                    "PF",
                ):
                    if (
                        stat not in window
                        or stat in window.attrs.get("imputed_stats", [])
                        or window[stat].isna().any()
                    ):
                        continue
                    value_stat = sum(
                        float(v) * f for v, f in zip(window[stat], factors)
                    ) / sum(factors)
                    prior_weight = (
                        dcfg.get("prior_weight_games", 12) if prior is not None else 0
                    )
                    if prior_weight:
                        value_stat = (
                            len(window) * value_stat
                            + prior_weight * float(older[stat].mean())
                        ) / (len(window) + prior_weight)
                    if math.isfinite(value_stat):
                        stats[stat] = round(value_stat, 2)
                profiles[pid] = {
                    "projected_fp": round(value, 2),
                    "projection_source": profile_source,
                    **counts,
                    "projected_stats": stats,
                    "as_of": str(reference.date()),
                    "scoring_notes": effective_weights(
                        normalize_stats_for_scoring(history), weights
                    )[1],
                    "sample_size": len(window),
                    "last_played": str(scored.GAME_DATE.max().date()),
                }
            except (DataUnavailable, ValueError, KeyError, TypeError):
                continue
    return profiles


def unavailable_lineup(reference, reason):
    return {
        "date": str(reference),
        "status": "unavailable",
        "reason": reason,
        "slots": [],
        "bench": [],
        "total_projected_fp": None,
        "filled_slots": 0,
        "eligible_players": 0,
        "missing_inputs": 0,
    }


def recommend_lineup(team, rows, profiles, reference, mode="live", blocked=None):
    date = str(reference)
    if blocked:
        return unavailable_lineup(date, blocked)
    slots = active_slots(team)
    if slots is None:
        return unavailable_lineup(
            date, "Sync Sleeper to load the league's full lineup configuration."
        )
    unknown = sorted(set(slots) - set(SLOTS))
    if unknown:
        return unavailable_lineup(
            date, "Unsupported lineup slots: " + ", ".join(unknown)
        )
    if not slots:
        return unavailable_lineup(
            date, "This league has no active lineup slots configured."
        )
    candidates, bench, seen = [], [], set()
    missing = scheduled = started = 0
    for row in rows:
        name, pid = row["player"], str(row.get("player_id") or "")
        identity = pid or name.casefold()
        if identity in seen:
            continue
        seen.add(identity)
        entry = {
            "player": name,
            "player_id": row.get("player_id"),
            "positions": row.get("positions", []),
            "current_slot": row.get("roster_slot"),
            "injury_status": row.get("injury_status"),
        }
        profile = row["projection"] if "projection" in row else profiles.get(pid)
        if profile:
            entry.update(profile)
        reason = None
        today_games = [g for g in row.get("week_games", []) if g["date"] == date]
        if row.get("roster_slot") in {"IR", "TAXI"}:
            reason = "Reserve slot"
        elif str(row.get("injury_status") or "").upper().replace(" ", "_") in OUT:
            reason = "Unavailable: " + str(row["injury_status"])
        elif row.get("schedule_state") != "verified":
            reason = "Schedule unavailable"
            missing += 1
        elif not today_games:
            reason = "No game today"
        elif any(
            g.get("status")
            not in {"pre_game", "in_progress", "complete", "final", "post_game"}
            for g in today_games
        ):
            reason = "Game postponed or unconfirmed"
            missing += 1
        elif mode == "live" and any(g.get("status") != "pre_game" for g in today_games):
            reason = "Game already started or finished"
            started += 1
        else:
            scheduled += 1
            if not profile:
                reason = "Projection unavailable"
                missing += 1
            elif not any(eligible(row.get("positions"), slot) for slot in slots):
                reason = (
                    "No eligible lineup slot"
                    if row.get("positions")
                    else "Position eligibility unavailable"
                )
                if not row.get("positions"):
                    missing += 1
            else:
                game = today_games[0]
                entry.update(
                    profile, opponent=game.get("opponent"), home=game.get("home")
                )
                candidates.append(entry)
        if reason:
            bench.append(dict(entry, reason=reason))
    assignment = optimal_assignment(slots, candidates)
    chosen = {i for i in assignment if i is not None}
    bench.extend(
        dict(p, reason="Lower projected total or position fit")
        for i, p in enumerate(candidates)
        if i not in chosen
    )
    filled = len(chosen)
    # All unknown projections is not a credible zero-point recommendation.
    status = (
        "partial"
        if missing
        else (
            "ready"
            if filled
            else "no_games" if not scheduled and not started else "empty"
        )
    )
    reason = {
        "partial": "Best lineup among players with verified schedules and projections; some inputs are missing.",
        "ready": "Maximum projected total across eligible players and league slots.",
        "no_games": "No available roster players have a scheduled game today.",
        "empty": (
            "Today's available games have already started or finished. No remaining starts to recommend."
            if started and not candidates
            else "No remaining eligible starts with a positive projected contribution."
        ),
    }[status]
    return {
        "date": date,
        "status": status,
        "reason": reason,
        "slots": [
            dict(
                slot=slot,
                slot_index=i,
                **(
                    candidates[player]
                    if player is not None
                    else {"player": None, "projected_fp": None}
                )
            )
            for i, (slot, player) in enumerate(zip(slots, assignment))
        ],
        "bench": bench,
        "total_projected_fp": (
            round(sum(candidates[i]["projected_fp"] for i in chosen), 2)
            if filled or not missing
            else None
        ),
        "filled_slots": filled,
        "eligible_players": len(candidates),
        "missing_inputs": missing,
    }
