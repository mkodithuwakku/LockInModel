"""Explainable rising-player screening. Scores are heuristics, not probabilities."""

import math
import numpy as np
import pandas as pd
from fetch_data import canonical_name, normalize_stats_for_scoring
from scoring import add_fantasy_points, apply_scoring_policy, scoring_notes
from model import rolling_baseline
from transport import DataUnavailable


def weighted(values, decay=0.92):
    values = np.asarray(values, dtype=float)
    w = decay ** np.arange(len(values) - 1, -1, -1)
    return float(np.average(values, weights=w))


def analyze_player(history, cfg):
    history = history.sort_values("GAME_DATE").tail(25)
    if len(history) < 13 or "MIN" not in history:
        return None
    recent = history.tail(5)
    previous = history.iloc[:-5].tail(20)
    base = rolling_baseline(previous, 20, cfg=cfg)
    mean = float(base["fp_mean"])
    sd = max(4, float(base["fp_std"]))
    recent_fp = weighted(recent.FP)
    lift = recent_fp - mean
    minutes = weighted(recent.MIN)
    old_minutes = float(previous.MIN.mean())
    consistency = float((recent.FP > mean).mean())
    # A spike without increased playing time receives a smaller forecast adjustment.
    role_factor = 1.0 if minutes - old_minutes >= 2 else 0.6
    prev_fga = float(previous.FGA.sum())
    recent_fga = float(recent.FGA.sum())
    old_efg = (
        float((previous.FGM.sum() + 0.5 * previous.FG3M.sum()) / prev_fga)
        if prev_fga
        else 0
    )
    new_efg = (
        float((recent.FGM.sum() + 0.5 * recent.FG3M.sum()) / recent_fga)
        if recent_fga
        else 0
    )
    shooting_spike = new_efg - old_efg > 0.12
    stock_spike = (
        float((recent.STL + recent.BLK).mean() - (previous.STL + previous.BLK).mean())
        > 1.5
    )
    sustain = (
        role_factor * (0.7 if shooting_spike else 1) * (0.75 if stock_spike else 1)
    )
    projection = mean + lift * consistency * sustain * 0.7
    signal = float(
        np.clip(
            35 * max(0, lift / sd)
            + 3 * max(0, minutes - old_minutes)
            + 20 * consistency,
            0,
            100,
        )
    )
    risks = []
    if shooting_spike:
        risks.append("Recent shooting efficiency may regress.")
    if stock_spike:
        risks.append("Elevated steals/blocks may be difficult to repeat.")
    if minutes - old_minutes < 2:
        risks.append("No substantial increase in playing time.")
    return {
        "recent_fp": round(recent_fp, 2),
        "baseline_fp": round(mean, 2),
        "lift": round(lift, 2),
        "lift_z": round(lift / sd, 2),
        "minutes": round(minutes, 1),
        "baseline_minutes": round(old_minutes, 1),
        "consistency": consistency,
        "projected_fp": round(projection, 2),
        "signal_score": round(signal),
        "games_recent": 5,
        "games_baseline": len(previous),
        "risks": risks,
        "qualifies": lift >= 4
        and lift / sd >= 0.5
        and consistency >= 0.6
        and minutes >= 18,
    }


def positions_compatible(a, b):
    def expand(values):
        out = set(values)
        if out & {"PG", "SG"}:
            out.add("G")
        if out & {"SF", "PF"}:
            out.add("F")
        return out

    return bool(expand(a) & expand(b)) if a and b else False


def find_pickups(games, team, cfg, reference, positions=None):
    team = apply_scoring_policy(dict(team))
    weights = team.get("weights") or cfg["weights"]
    observed = games[
        (games.GAME_DATE <= pd.Timestamp(reference))
        & (games.GAME_DATE >= pd.Timestamp(reference) - pd.Timedelta(days=90))
    ]
    scored = add_fantasy_points(normalize_stats_for_scoring(observed), weights)
    positions = positions or {}
    owned = {canonical_name(n) for n in team.get("owned_players", team["players"])}
    mine = {canonical_name(n) for n in team["players"]}
    starters = {canonical_name(n) for n in team["starters"]}
    profiles = {}
    for pid, h in scored.groupby("PLAYER_ID"):
        signal = analyze_player(h, cfg)
        if signal:
            name = str(h.iloc[-1].PLAYER_NAME)
            profiles[canonical_name(name)] = {
                "player": name,
                "player_id": str(pid),
                "nba_team": str(h.iloc[-1].get("TEAM_ABBREVIATION", "")),
                "positions": positions.get(
                    canonical_name(name), [str(h.iloc[-1].get("POSITION", ""))]
                ),
                "last_played": str(h.GAME_DATE.max().date()),
                **signal,
            }
    candidates = []
    for key, item in profiles.items():
        if key in owned or not item["qualifies"]:
            continue
        # Don't rank a player who has not appeared within the last 7 days as rising.
        if (pd.Timestamp(reference) - pd.Timestamp(item["last_played"])).days > 7:
            continue
        alternatives = [
            p
            for k, p in profiles.items()
            if k in mine and positions_compatible(item["positions"], p["positions"])
        ]
        bench = [p for p in alternatives if canonical_name(p["player"]) not in starters]
        replacement = min(
            bench or alternatives, key=lambda p: p["projected_fp"], default=None
        )
        item.update(
            replacement=replacement["player"] if replacement else None,
            team_gain=(
                round(item["projected_fp"] - replacement["projected_fp"], 2)
                if replacement
                else None
            ),
            availability=(
                "Unrostered at latest Sleeper sync"
                if team.get("ownership_complete")
                else "League ownership unknown"
            ),
            ownership_as_of=team.get("synced_at"),
            scoring_complete=not bool(team.get("unsupported_scoring")),
        )
        item["risks"].extend(scoring_notes(team, observed, weights))
        if team.get("unsupported_scoring"):
            item["risks"].append(
                "Estimate excludes unsupported league scoring; verify before adding."
            )
        candidates.append(item)
    return sorted(
        candidates, key=lambda p: (p["signal_score"], p["team_gain"] or 0), reverse=True
    )[:30]


def available_players(team, directory, games=None, cfg=None):
    """A verified ownership directory, independent of history or rising signals."""
    if not team.get("ownership_complete"):
        return []
    from fetch_data import player_directory

    identities = player_directory()
    summaries = {}
    if games is not None and not games.empty and cfg is not None:
        policy = apply_scoring_policy(dict(team))
        if not policy.get("unsupported_scoring"):
            try:
                scored = add_fantasy_points(
                    normalize_stats_for_scoring(games),
                    policy.get("weights") or cfg["weights"],
                )
            except (DataUnavailable, ValueError):
                # Directory browsing must survive unavailable scoring inputs.
                scored = pd.DataFrame(columns=["PLAYER_ID"])
            for _, history in scored.groupby("PLAYER_ID"):
                history = history.sort_values("GAME_DATE").tail(10)
                recent = float(history.tail(5).FP.mean())
                baseline = (
                    float(history.head(5).FP.mean()) if len(history) == 10 else None
                )
                summaries[canonical_name(str(history.iloc[-1].PLAYER_NAME))] = {
                    "recent_fp": round(recent, 2),
                    "games_recent": min(5, len(history)),
                    "baseline_fp": round(baseline, 2) if baseline is not None else None,
                    "lift": (
                        round(recent - baseline, 2) if baseline is not None else None
                    ),
                }
    owned = {
        canonical_name(n)
        for n in team.get("owned_players", []) + team.get("players", [])
    }
    owned_ids = {str(pid) for pid in team.get("owned_player_ids", [])}
    result = []
    for sid, player in directory.items():
        name = (
            player.get("full_name")
            or " ".join(
                [player.get("first_name", ""), player.get("last_name", "")]
            ).strip()
        )
        positions = player.get("fantasy_positions") or []
        if (
            not name
            or player.get("active") is not True
            or not set(positions) & {"PG", "SG", "SF", "PF", "C"}
            or str(sid) in owned_ids
            or canonical_name(name) in owned
        ):
            continue
        pid = identities.get(canonical_name(name))
        result.append(
            {
                "player": name,
                "player_id": str(pid) if pid else None,
                "nba_team": player.get("team") or player.get("team_abbr"),
                "positions": positions,
                "injury_status": player.get("injury_status"),
                "ownership_as_of": team.get("synced_at"),
                **summaries.get(canonical_name(name), {}),
            }
        )
    return sorted(
        result, key=lambda p: (not bool(p["nba_team"]), canonical_name(p["player"]))
    )
