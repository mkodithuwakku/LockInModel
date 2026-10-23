"""Daily pregame projections and exact maximum-weight slot assignment."""

import math

import pandas as pd

from fetch_data import normalize_stats_for_scoring, canonical_name
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
                    .get(str(history.iloc[-1].PLAYER_NAME), {}),
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


def apply_opponent_model(
    rows,
    profiles,
    league_games,
    positions,
    weights,
    cfg,
    reference,
    schedule=None,
    min_games=None,
):
    """Opponent-aware Ridge projections for every unplayed ``week_games`` tile.

    Returns ``{(player_id, 'YYYY-MM-DD'): fp}`` for eligible tiles and overlays
    tonight's matching profiles with ``projection_source: "opponent_ridge"``.
    Eligible players need a verified target game and at least ``min_games``
    prior observations; training uses every league game, not just roster rows.
    Any failure (sparse data, unconfirmed opponent, fitting errors) leaves the
    baseline profile untouched — the fallback is never a zero forecast.

    Hyperparameters come from ``model_ml.model_settings(cfg)`` so
    ``evaluator.py --mode tune`` recommendations applied to ``cfg['model']``
    take effect here without code changes.
    """
    ref = str(pd.Timestamp(reference).date())
    targets = []
    for row in rows:
        pid = str(row.get("player_id") or "")
        team = row.get("nba_team")
        if not pid or not team:
            continue
        for game in row.get("week_games") or []:
            if game.get("status") not in ("pre_game", "scheduled") or not game.get(
                "opponent"
            ):
                continue
            targets.append(
                {
                    "PLAYER_ID": pid,
                    "GAME_DATE": str(game["date"]),
                    "TEAM_ABBREVIATION": team,
                    "OPPONENT": game["opponent"],
                    "IS_HOME": int(bool(game.get("home"))),
                }
            )
    if not targets or league_games is None or len(league_games) == 0:
        return {}
    try:
        from features import FeatureBuilder
        from model_ml import ComponentRidge, model_settings

        settings = model_settings(cfg)
        if min_games is None:
            min_games = settings["min_player_games"]
        reference = pd.Timestamp(reference)
        counts = league_games.groupby(league_games.PLAYER_ID.astype(str)).size()
        eligible = [
            t
            for t in targets
            if counts.get(t["PLAYER_ID"], 0) >= min_games
            and t.get("OPPONENT")
            and t.get("TEAM_ABBREVIATION")
        ]
        if not eligible:
            return {}
        builder = FeatureBuilder(
            league_games,
            positions=positions,
            schedule=schedule,
            window=settings["feature_window"],
            decay=settings["player_decay"],
            lookback=settings["player_lookback"],
        )
        matrix = builder.training_matrix()
        matrix["GAME_DATE"] = pd.to_datetime(matrix.GAME_DATE)
        # Strictly pregame: same-day observations never train a forecast,
        # matching the baseline's pregame contract.
        train = matrix[matrix.GAME_DATE < reference]
        if len(train) < settings["min_train_rows"]:
            return {}
        # Weights are only needed for FP residuals (lock probabilities); tiles
        # rescore via each league's formula, so fit components only.
        model = ComponentRidge(lam=settings["ridge_lambda"]).fit(train)
        if not model.betas:
            return {}
        feats = builder.features_for(pd.DataFrame(eligible))
        stats = model.predict_components(feats)
        tile_map = {}
        for index, target in enumerate(eligible):
            pid = str(target["PLAYER_ID"])
            profile = profiles.get(pid)
            if profile is None:
                continue
            try:
                # Ridge components overlay the baseline's full box estimate so
                # any league formula (incl. FGA/FTM weights, milestone bonuses)
                # scores through add_fantasy_points unchanged.
                merged = dict(profile.get("projected_stats") or {})
                merged.update(
                    {
                        stat: round(float(stats.iloc[index][stat]), 2)
                        for stat in stats.columns
                    }
                )
                scored = pd.DataFrame(
                    [
                        dict(
                            merged,
                            GAME_DATE=pd.Timestamp(target["GAME_DATE"]),
                            PLAYER_ID=pid,
                        )
                    ]
                )
                value = float(add_fantasy_points(scored, weights).FP.iloc[0])
                if not math.isfinite(value):
                    continue
                tile_map[(pid, target["GAME_DATE"])] = round(value, 2)
                if target["GAME_DATE"] == ref:
                    profile = dict(profile)
                    profile.update(
                        projected_fp=round(value, 2),
                        projected_stats=merged,
                        projection_source="opponent_ridge",
                    )
                    profiles[pid] = profile
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
        return tile_map
    except Exception as exc:  # baseline profiles always remain serviceable
        from logger import get_logger

        get_logger(__name__).warning("Opponent model unavailable: %s", exc)
        return {}


def lock_match(row, record):
    """A lock record identifies a roster player by Sleeper id, then name."""
    pid = str(record.get("player_id") or "").strip()
    if pid and (
        str(row.get("sleeper_id") or "") == pid
        or str(row.get("player_id") or "") in {pid, "sleeper:" + pid}
    ):
        return True
    name = record.get("canonical_name") or record.get("player_name")
    return bool(name) and canonical_name(
        str(row.get("player") or "")
    ) == canonical_name(str(name))


def _pin_index(row, record, slots, pinned):
    """The locked slot is the player's current synced slot, not a free choice."""
    name = row.get("roster_slot") or record.get("roster_slot")
    if name not in slots:
        name = record.get("roster_slot")
    if name not in slots:
        return None
    for candidate in (record.get("slot_index"), row.get("lineup_order")):
        if (
            isinstance(candidate, int)
            and not isinstance(candidate, bool)
            and 0 <= candidate < len(slots)
            and slots[candidate] == name
            and candidate not in pinned
        ):
            return candidate
    return next(
        (i for i, slot in enumerate(slots) if slot == name and i not in pinned),
        None,
    )


def locked_score(record):
    value = record.get("locked_fp")
    return value if type(value) in (int, float) and math.isfinite(value) else None


# Bench reasons that may hold an open slot as a zero-FP placeholder: healthy
# roster players who simply cannot start right now. Reserve, out/injured and
# actively-playing candidates stay on the bench.
PLACEHOLDER_REASONS = frozenset(
    {
        "No game today",
        "Game already started or finished",
        "Game postponed or unconfirmed",
        "Schedule unavailable",
        "Projection unavailable",
    }
)


def unavailable_lineup(reference, reason):
    return {
        "date": str(reference),
        "status": "unavailable",
        "reason": reason,
        "slots": [],
        "bench": [],
        "total_projected_fp": None,
        "filled_slots": 0,
        "pinned_slots": 0,
        "eligible_players": 0,
        "missing_inputs": 0,
        "pin_warnings": [],
    }


def recommend_lineup(
    team, rows, profiles, reference, mode="live", blocked=None, locks=None
):
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
    # Locked-in Sleeper starters stay pinned: their slots never re-enter the
    # assignment pool, even on off days or negative banked scores.
    pinned, pin_warnings = {}, []
    for record in locks.values() if isinstance(locks, dict) else (locks or []):
        if not isinstance(record, dict):
            continue
        hit = next((i for i, row in enumerate(rows) if lock_match(row, record)), None)
        name = record.get("player_name") or str(record.get("player_id") or "?")
        if hit is None:
            pin_warnings.append(f"Locked player {name} is no longer on this roster.")
            continue
        row = rows[hit]
        if row.get("roster_slot") in RESERVE:
            pin_warnings.append(f"Locked player {row['player']} is in a reserve slot.")
            continue
        index = _pin_index(row, record, slots, pinned)
        if index is None:
            pin_warnings.append(
                f"No {row.get('roster_slot')} slot remains for locked player {row['player']}."
            )
            continue
        pinned[index] = (hit, record)
    pinned_rows = {hit for hit, _ in pinned.values()}
    candidates, bench, seen = [], [], set()
    missing = scheduled = started = 0
    for row_index, row in enumerate(rows):
        if row_index in pinned_rows:
            continue
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
    remaining = [slot for i, slot in enumerate(slots) if i not in pinned]
    assignment = optimal_assignment(remaining, candidates) if remaining else []
    chosen = {i for i in assignment if i is not None}
    bench.extend(
        dict(p, reason="Lower projected total or position fit")
        for i, p in enumerate(candidates)
        if i not in chosen
    )

    def pinned_entry(row, record):
        entry = {
            "player": row["player"],
            "player_id": row.get("player_id"),
            "positions": row.get("positions", []),
            "current_slot": row.get("roster_slot"),
            "injury_status": row.get("injury_status"),
        }
        profile = (
            row["projection"]
            if "projection" in row
            else profiles.get(str(row.get("player_id") or ""))
        )
        if profile:
            entry.update(profile)
        today_games = [g for g in row.get("week_games", []) if g["date"] == date]
        if today_games:
            entry.update(
                opponent=today_games[0].get("opponent"),
                home=today_games[0].get("home"),
            )
        locked_fp = locked_score(record)
        entry.update(
            projected_fp=(
                locked_fp if locked_fp is not None else entry.get("projected_fp")
            ),
            is_pinned=True,
            is_locked=True,
            locked_fp=locked_fp,
            lock_game_date=record.get("game_date"),
            lineup_reason="Pinned starter (locked in Sleeper)",
        )
        return entry

    merged, cursor = [], 0
    for i, slot in enumerate(slots):
        if i in pinned:
            hit, record = pinned[i]
            merged.append(
                dict(
                    slot=slot,
                    slot_index=i,
                    **pinned_entry(rows[hit], record),
                )
            )
            continue
        player = assignment[cursor]
        cursor += 1
        merged.append(
            dict(
                slot=slot,
                slot_index=i,
                **(
                    candidates[player]
                    if player is not None
                    else {"player": None, "projected_fp": None}
                ),
            )
        )
    filled = len(chosen) + len(pinned)
    # Placeholder fill: healthy benched players hold open slots so the sheet
    # never renders an empty lineup. They add nothing to the projected total.
    vacant = [i for i, entry in enumerate(merged) if entry["player"] is None]
    idle = [p for p in bench if p["reason"] in PLACEHOLDER_REASONS]
    if vacant and idle:
        pool = [
            dict(
                p,
                projected_fp=(
                    p["projected_fp"]
                    if isinstance(p.get("projected_fp"), (int, float))
                    and math.isfinite(p["projected_fp"])
                    else 0
                ),
            )
            for p in idle
        ]
        placement = optimal_assignment([merged[i]["slot"] for i in vacant], pool)
        used = set()
        for j, pick in enumerate(placement):
            if pick is None:
                continue
            i = vacant[j]
            used.add(id(idle[pick]))
            merged[i] = dict(
                slot=merged[i]["slot"],
                slot_index=i,
                **idle[pick],
                off_day=True,
                lineup_reason=(
                    f"{idle[pick]['reason']} — holding the slot so your roster stays visible"
                ),
            )
        if used:
            bench = [p for p in bench if id(p) not in used]
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
        "ready": (
            "Maximum projected total across eligible players and unlocked league slots."
            if pinned
            else "Maximum projected total across eligible players and league slots."
        ),
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
        "slots": merged,
        "bench": bench,
        "total_projected_fp": (
            round(
                sum(candidates[i]["projected_fp"] for i in chosen)
                + sum(
                    fp
                    for fp in (merged[i].get("projected_fp") for i in pinned)
                    if type(fp) in (int, float)
                ),
                2,
            )
            if filled or not missing
            else None
        ),
        "filled_slots": filled,
        "pinned_slots": len(pinned),
        "eligible_players": len(candidates),
        "missing_inputs": missing,
        "pin_warnings": pin_warnings,
    }
