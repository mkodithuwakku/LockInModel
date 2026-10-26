"""Season production for the current roster, not historical ownership/locked totals."""

import math
import pandas as pd
from fetch_data import normalize_stats_for_scoring
from scoring import add_fantasy_points, effective_weights
from transport import DataUnavailable

STATS = (
    "PTS",
    "REB",
    "AST",
    "STL",
    "BLK",
    "FG3M",
    "TOV",
    "MIN",
    "FGM",
    "FGA",
    "FTM",
    "FTA",
    "FG3A",
    "OREB",
    "DREB",
    "PF",
)


def production_stats(frame):
    """Observed totals and attempt-weighted rates; never use imputed box stats."""
    stats = {
        k: round(float(frame[k].sum()), 2)
        for k in STATS
        if k in frame
        and k not in frame.attrs.get("imputed_stats", [])
        and frame[k].notna().all()
    }

    def ratio(numerator, denominator, scale=1):
        return (
            round(numerator / denominator * scale, 2)
            if numerator is not None and denominator is not None and denominator > 0
            else None
        )

    stats["FG_PCT"] = ratio(stats.get("FGM"), stats.get("FGA"), 100)
    stats["FT_PCT"] = ratio(stats.get("FTM"), stats.get("FTA"), 100)
    stats["FG3_PCT"] = ratio(stats.get("FG3M"), stats.get("FG3A"), 100)
    stats["EFG_PCT"] = ratio(
        (
            stats["FGM"] + 0.5 * stats["FG3M"]
            if "FGM" in stats and "FG3M" in stats
            else None
        ),
        stats.get("FGA"),
        100,
    )
    stats["TS_PCT"] = ratio(
        stats.get("PTS"),
        (
            2 * (stats["FGA"] + 0.44 * stats["FTA"])
            if "FGA" in stats and "FTA" in stats
            else None
        ),
        100,
    )
    stats["AST_TOV"] = ratio(stats.get("AST"), stats.get("TOV"))
    stats["FP_PER_MIN"] = ratio(float(frame.FP.sum()), stats.get("MIN"))
    return stats


def season_game_log(scored, roster, weights):
    """Full observed season tape with league-scored components and prior-only context."""
    import re

    identities = {str(r.get("player_id")): r for r in roster}
    effective, notes = effective_weights(scored, weights)
    components = {
        stat: add_fantasy_points(scored, {stat: weight}).FP
        for stat, weight in effective.items()
        if weight
    }
    missing = set(scored.attrs.get("imputed_stats", []))
    history = {}
    tape = []
    for index, game in scored.iterrows():
        pid = str(game.PLAYER_ID)
        prior = history.setdefault(pid, [])
        earlier = [p for p in prior if p["date"] < game.GAME_DATE]
        baseline = (
            sum(p["fp"] for p in earlier[-10:]) / min(10, len(earlier))
            if len(earlier) >= 3
            else None
        )
        matchup = str(game.get("MATCHUP", ""))
        match = re.fullmatch(r"[A-Z]{2,4}\s+(vs\.?|@)\s+([A-Z]{2,4})", matchup)
        categories = ["PTS", "REB", "AST", "STL", "BLK"]
        doubles = (
            sum(game.get(k, 0) >= 10 for k in categories)
            if not missing.intersection(categories)
            else None
        )
        tape.append(
            dict(
                player_id=pid,
                player=identities[pid]["player"],
                game_id=str(game.get("GAME_ID", game.GAME_DATE.date())),
                date=str(game.GAME_DATE.date()),
                fp=round(float(game.FP), 4),
                stats={
                    k: (
                        float(game[k])
                        if k in game and k not in missing and pd.notna(game[k])
                        else None
                    )
                    for k in STATS
                },
                scoring={
                    k: round(float(values.loc[index]), 4)
                    for k, values in components.items()
                },
                opponent=match[2] if match else None,
                venue=("away" if match[1] == "@" else "home") if match else None,
                result=(
                    str(game.get("WL")) if str(game.get("WL")) in ("W", "L") else None
                ),
                days_since_previous=(
                    (game.GAME_DATE - prior[-1]["date"]).days if prior else None
                ),
                baseline_fp=round(baseline, 4) if baseline is not None else None,
                baseline_games=min(10, len(earlier)),
                delta=(
                    round(float(game.FP) - baseline, 4)
                    if baseline is not None
                    else None
                ),
                double_double=doubles >= 2 if doubles is not None else None,
                triple_double=doubles >= 3 if doubles is not None else None,
            )
        )
        prior.append({"fp": float(game.FP), "date": game.GAME_DATE})
    return (
        tape,
        [{"stat": k, "weight": float(v)} for k, v in effective.items() if v],
        notes,
    )


def season_review(
    games,
    roster,
    weights,
    reference,
    unavailable=False,
    season=None,
    include_games=True,
):
    ref = pd.Timestamp(reference)
    year = (
        int(str(season)[:4])
        if season and str(season)[:4].isdigit()
        else ref.year - (ref.month < 10)
    )
    start = pd.Timestamp(year=year, month=10, day=1)
    end = min(ref, pd.Timestamp(year=year + 1, month=9, day=30))
    base = dict(
        season=f"{year}–{str(year+1)[-2:]}",
        as_of=str(end.date()),
        scope="current_roster",
        status="unavailable" if unavailable else "empty",
        roster_count=len(roster),
        covered_players=0,
        appearances=0,
        total_fp=None,
        fp_per_game=None,
        top_three_share=None,
        stats={},
        weeks=[],
        players=[],
        game_log=[],
        scoring_rules=[],
        scoring_notes=[],
    )
    if unavailable or games is None or games.empty:
        return base
    ids = {str(r["player_id"]) for r in roster if r.get("player_id")}
    frame = games[
        games.PLAYER_ID.astype(str).isin(ids) & games.GAME_DATE.between(start, end)
    ].copy()
    if frame.empty:
        return base
    frame["PLAYER_ID"] = frame.PLAYER_ID.astype(str)
    frame = frame.drop_duplicates(
        ["PLAYER_ID"] + (["GAME_ID"] if "GAME_ID" in frame else ["GAME_DATE"]),
        keep="last",
    )
    try:
        scored = (
            add_fantasy_points(normalize_stats_for_scoring(frame), weights)
            .sort_values("GAME_DATE")
            .reset_index(drop=True)
        )
    except (DataUnavailable, ValueError, KeyError, TypeError):
        return dict(base, status="unavailable")
    scored["PLAYER_ID"] = scored.PLAYER_ID.astype(str)
    groups = {pid: h for pid, h in scored.groupby("PLAYER_ID")}
    players = []
    seen = set()
    for row in roster:
        pid = str(row.get("player_id") or "")
        if not pid or pid in seen or pid not in groups:
            continue
        seen.add(pid)
        h = groups[pid]
        recent = h.tail(5).FP
        old = h.iloc[-10:-5].FP
        players.append(
            dict(
                player_id=pid,
                player=row["player"],
                nba_team=row.get("nba_team"),
                positions=row.get("positions") or [],
                stats=production_stats(h),
                games=len(h),
                total_fp=round(float(h.FP.sum()), 2),
                average_fp=round(float(h.FP.mean()), 2),
                recent_fp=round(float(recent.mean()), 2),
                recent_games=len(recent),
                change=(
                    round(float(recent.mean() - old.mean()), 2)
                    if len(h) >= 10
                    else None
                ),
                spread=round(float(h.FP.std(ddof=0)), 2) if len(h) >= 5 else None,
                best_fp=round(float(h.FP.max()), 2),
                floor_fp=round(float(h.FP.quantile(0.25)), 2) if len(h) >= 5 else None,
                ceiling_fp=(
                    round(float(h.FP.quantile(0.75)), 2) if len(h) >= 5 else None
                ),
                best_date=str(h.loc[h.FP.idxmax(), "GAME_DATE"].date()),
                last_played=str(h.GAME_DATE.max().date()),
            )
        )
    players.sort(key=lambda p: (-p["total_fp"], p["player"]))
    positive = sum(max(0, p["total_fp"]) for p in players)
    for p in players:
        p["share"] = (
            round(max(0, p["total_fp"]) / positive * 100, 1) if positive else None
        )
    stats = production_stats(scored)
    weeks = []
    week = scored.GAME_DATE - pd.to_timedelta(scored.GAME_DATE.dt.weekday, unit="D")
    for day, h in scored.groupby(week):
        weeks.append(
            dict(
                date=str(day.date()),
                total_fp=round(float(h.FP.sum()), 2),
                average_fp=round(float(h.FP.mean()), 2),
                games=len(h),
            )
        )
    tape, rules, notes = (
        season_game_log(scored, roster, weights) if include_games else ([], [], [])
    )
    return dict(
        base,
        status="ready",
        covered_players=len(players),
        appearances=len(scored),
        total_fp=round(float(scored.FP.sum()), 2),
        fp_per_game=round(float(scored.FP.mean()), 2),
        top_three_share=(
            round(sum(max(0, p["total_fp"]) for p in players[:3]) / positive * 100, 1)
            if positive
            else None
        ),
        stats=stats,
        weeks=weeks,
        players=players,
        game_log=tape,
        scoring_rules=rules,
        scoring_notes=notes,
    )


def weekly_film(games, rows, slots, locks, week, weights):
    """Hindsight audit of one matchup week's recorded lock calls.

    Retained total = recorded locked scores + the best legal end-of-week fill
    of the remaining slots using each unlocked roster player's best game.
    Oracle = the best legal assignment of everyone's best game over every slot.
    A lock is flagged when unpinning it and re-filling would have scored more:
    the same player refilling means a timing mistake, someone else means the
    wrong player was locked. Scores are heuristics over completed games, not
    predictive claims.
    """
    from lineup import lock_match, optimal_assignment, _pin_index

    base = dict(
        status="empty",
        locked_count=0,
        clean_count=0,
        retained_fp=None,
        oracle_fp=None,
        regret_fp=None,
        efficiency=None,
        mistakes=[],
        locked=[],
        performances=[],
        note=None,
    )
    if not slots:
        return dict(base, status="unavailable", note="Lineup slots unavailable.")
    if not week or not week[0] or not week[1]:
        return dict(base, status="unavailable", note="Review week unavailable.")
    if games is None or games.empty:
        return base
    ids = {str(r.get("player_id")) for r in rows if r.get("player_id")}
    games = games.copy()
    games["PLAYER_ID"] = games.PLAYER_ID.astype(str)
    games = (
        games.drop_duplicates(
            ["PLAYER_ID"] + (["GAME_ID"] if "GAME_ID" in games else ["GAME_DATE"]),
            keep="last",
        )
        .sort_values("GAME_DATE")
        .reset_index(drop=True)
    )
    frame = games[
        games.PLAYER_ID.astype(str).isin(ids)
        & games.GAME_DATE.between(pd.Timestamp(week[0]), pd.Timestamp(week[1]))
    ]
    if frame.empty:
        return base
    try:
        scored = add_fantasy_points(normalize_stats_for_scoring(frame), weights)
    except (DataUnavailable, ValueError, KeyError, TypeError):
        return dict(base, status="unavailable", note="Scoring inputs unavailable.")
    # Only preceding observations enter a game's benchmark, never its result.
    performances = []
    identities = {str(r.get("player_id")): r for r in rows}
    for game in scored.itertuples():
        pid = str(game.PLAYER_ID)
        prior = games[
            (games.PLAYER_ID == pid) & (games.GAME_DATE < game.GAME_DATE)
        ].tail(10)
        baseline = None
        if len(prior) >= 3:
            try:
                baseline = float(
                    add_fantasy_points(
                        normalize_stats_for_scoring(prior), weights
                    ).FP.mean()
                )
            except (DataUnavailable, ValueError, KeyError, TypeError):
                pass
        performances.append(
            dict(
                player_id=pid,
                player=identities[pid]["player"],
                date=str(game.GAME_DATE.date()),
                fp=round(float(game.FP), 2),
                baseline_fp=round(baseline, 2) if baseline is not None else None,
                baseline_games=len(prior),
                delta=(
                    round(float(game.FP) - baseline, 2)
                    if baseline is not None
                    else None
                ),
                **{
                    k.lower(): (
                        float(getattr(game, k))
                        if k not in scored.attrs.get("imputed_stats", [])
                        and pd.notna(getattr(game, k, None))
                        else None
                    )
                    for k in ("PTS", "REB", "AST", "TOV")
                },
            )
        )
    base["performances"] = performances
    best = {}
    for pid, h in scored.groupby("PLAYER_ID"):
        top = h.loc[h.FP.idxmax()]
        best[str(pid)] = {
            "fp": float(top.FP),
            "date": str(top.GAME_DATE.date()),
            "by_date": {str(g.GAME_DATE.date()): float(g.FP) for g in h.itertuples()},
        }
    candidates = []
    for row in rows:
        pid = str(row.get("player_id") or "")
        b = best.get(pid)
        if not b or row.get("roster_slot") in {"IR", "TAXI"}:
            continue
        candidates.append(
            {
                "row": row,
                "player": row.get("player"),
                "player_id": pid,
                "positions": row.get("positions") or [],
                "projected_fp": b["fp"],
                "best_date": b["date"],
            }
        )

    pinned = {}
    locked = []
    for record in (locks or {}).values():
        if not isinstance(record, dict):
            continue
        row = next((r for r in rows if lock_match(r, record)), None)
        if row is None:
            continue
        index = _pin_index(row, record, slots, set(pinned))
        if index is None:
            continue
        pid = str(row.get("player_id") or "")
        fp = record.get("locked_fp")
        if not isinstance(fp, (int, float)) or not math.isfinite(fp):
            day = best.get(pid, {}).get("by_date", {}).get(record.get("game_date"))
            fp = day if day is not None else best.get(pid, {}).get("fp")
        if not isinstance(fp, (int, float)) or not math.isfinite(fp):
            continue
        pinned[index] = {"row": row, "record": record, "fp": float(fp)}
        locked.append(
            {
                "player": row.get("player"),
                "player_id": pid,
                "slot": slots[index],
                "fp": round(float(fp), 2),
                "date": record.get("game_date"),
            }
        )
    open_index = [i for i in range(len(slots)) if i not in pinned]
    pinned_ids = {str(p["row"].get("player_id")) for p in pinned.values()}
    free = [c for c in candidates if c["player_id"] not in pinned_ids]
    fill = optimal_assignment([slots[i] for i in open_index], free)
    retained = sum(p["fp"] for p in pinned.values()) + sum(
        free[j]["projected_fp"] for j in fill if j is not None
    )
    oracle_fill = optimal_assignment(slots, candidates)
    oracle = sum(candidates[j]["projected_fp"] for j in oracle_fill if j is not None)
    mistakes = []
    clean = 0
    for index, p in pinned.items():
        alt_index = [i for i in range(len(slots)) if i != index and i not in pinned]
        # Unpin this lock: its slot rejoins the open pool and the player
        # re-enters contention with their weekly best. Other pinned players
        # stay locked at their recorded scores, so they leave the pool.
        other_ids = pinned_ids - {str(p["row"].get("player_id"))}
        alt_pool = [c for c in candidates if c["player_id"] not in other_ids]
        alt_slots = [slots[index]] + [slots[i] for i in alt_index]
        alt_fill = optimal_assignment(alt_slots, alt_pool)
        alt_total = sum(v["fp"] for k, v in pinned.items() if k != index) + sum(
            alt_pool[j]["projected_fp"] for j in alt_fill if j is not None
        )
        cost = alt_total - retained
        if cost <= 0.5:
            clean += 1
            continue
        pid_i = str(p["row"].get("player_id"))
        kept = {alt_pool[j]["player_id"] for j in alt_fill if j is not None}
        # Right player, wrong night: the locked player still makes the alt
        # lineup but his better game beats the recorded lock — a different
        # game of his was the play, whichever slot the cascade seats him in.
        own_best = best.get(pid_i)
        timing = (
            pid_i in kept and own_best is not None and own_best["fp"] > p["fp"] + 0.5
        )
        j = alt_fill[0]
        better = alt_pool[j] if j is not None else None
        mistakes.append(
            {
                "player": p["row"].get("player"),
                "player_id": pid_i,
                "slot": slots[index],
                "locked_fp": round(p["fp"], 2),
                "locked_date": p["record"].get("game_date"),
                "kind": "timing" if timing else "player",
                "better_player": (
                    p["row"].get("player")
                    if timing
                    else better["player"] if better else None
                ),
                "better_player_id": (
                    pid_i if timing else (better["player_id"] if better else None)
                ),
                "better_fp": (
                    round(own_best["fp"], 2)
                    if timing
                    else round(better["projected_fp"], 2) if better else None
                ),
                "better_date": (
                    own_best["date"]
                    if timing
                    else better["best_date"] if better else None
                ),
                "cost_fp": round(float(cost), 1),
            }
        )
    mistakes.sort(key=lambda m: -m["cost_fp"])
    return dict(
        base,
        status="ready",
        locked_count=len(locked),
        clean_count=clean,
        retained_fp=round(retained, 1),
        oracle_fp=round(oracle, 1),
        regret_fp=round(oracle - retained, 1),
        efficiency=round(retained / oracle * 100, 1) if oracle else None,
        mistakes=mistakes,
        locked=sorted(locked, key=lambda l: (l["date"] or "", l["slot"])),
    )
