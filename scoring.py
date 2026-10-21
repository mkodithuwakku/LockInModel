"""League scoring, derived milestones, and explicit approximation policies."""

import math
import re
import numpy as np
import pandas as pd

BASE_STATS = {
    "PTS",
    "REB",
    "AST",
    "STL",
    "BLK",
    "TOV",
    "FG3M",
    "FGM",
    "FGA",
    "FTM",
    "FTA",
    "OREB",
    "DREB",
    "PF",
}
IGNORED_LEAGUE_SCORING = {"ff", "tf"}
BONUS_STATS = {"pt": "PTS", "reb": "REB", "ast": "AST", "stl": "STL", "blk": "BLK"}


def milestone(stat):
    match = re.fullmatch(r"(PTS|REB|AST|STL|BLK)([1-9][0-9]*)", stat)
    return (match[1], int(match[2])) if match else None


def supported_stat(stat):
    return isinstance(stat, str) and (
        stat in BASE_STATS | {"DD", "TD"} or milestone(stat) is not None
    )


def sleeper_bonus(key):
    match = re.fullmatch(r"bonus_(pt|reb|ast|stl|blk)_([1-9][0-9]*)p", key)
    return BONUS_STATS[match[1]] + match[2] if match else None


def apply_scoring_policy(team):
    """Migrate saved and newly imported rules without losing original penalties."""
    unsupported = dict(team.get("unsupported_scoring", {}))
    ignored = dict(team.get("ignored_scoring", {}))
    weights = dict(team.get("weights", {}))
    for key in list(unsupported):
        if key in IGNORED_LEAGUE_SCORING:
            ignored[key] = unsupported.pop(key)
        else:
            stat = {"oreb": "OREB", "dreb": "DREB", "pf": "PF"}.get(
                key
            ) or sleeper_bonus(key)
            if stat:
                weights[stat] = unsupported.pop(key)
    if weights:
        team["weights"] = weights
    team["ignored_scoring"] = ignored
    team["unsupported_scoring"] = unsupported
    return team


def effective_weights(df, weights):
    """Use observed splits/fouls when complete, otherwise the approved approximation."""
    weights = {k: float(v) for k, v in weights.items()}
    if not all(math.isfinite(v) for v in weights.values()):
        raise ValueError("Fantasy weights must be finite.")
    imputed = set(df.attrs.get("imputed_stats", []))

    def available(stat):
        return (
            stat in df
            and stat not in imputed
            and np.isfinite(pd.to_numeric(df[stat], errors="coerce")).all()
        )

    notes = []
    if weights.get("PF") and not available("PF"):
        weights.pop("PF")
        notes.append(
            "Personal-foul penalties omitted because the box scores lack them."
        )
    split = [stat for stat in ("OREB", "DREB") if weights.get(stat)]
    if split and not all(available(stat) for stat in split):
        # Without a split, assign equal likelihood to offensive/defensive rebounds.
        # Equal split weights are exact; unequal weights are an explicit estimate.
        coefficient = (weights.pop("OREB", 0) + weights.pop("DREB", 0)) / 2
        weights["REB"] = weights.get("REB", 0) + coefficient
        notes.append(
            f"Rebound splits unavailable; total rebounds use {weights['REB']:g} FP each (base weight plus the mean of the two split weights)."
        )
    return weights, notes


def scoring_notes(team, df, weights):
    notes = effective_weights(df, weights)[1]
    if team.get("ignored_scoring"):
        notes.insert(
            0,
            "Unavailable foul penalties omitted: "
            + ", ".join(sorted(team["ignored_scoring"]))
            + ".",
        )
    return notes


def add_fantasy_points(df: pd.DataFrame, weights: dict) -> pd.DataFrame:
    out = df.copy()
    out["FP"] = 0.0
    weights, _ = effective_weights(df, weights)
    imputed = set(df.attrs.get("imputed_stats", []))

    def values(stat):
        if stat not in out or stat in imputed:
            raise ValueError("Missing weighted stat: " + stat)
        result = pd.to_numeric(out[stat], errors="coerce")
        if not np.isfinite(result).all():
            raise ValueError("Invalid weighted stat: " + stat)
        return result

    for stat, weight in weights.items():
        if weight == 0:
            continue
        threshold = milestone(stat)
        if threshold:
            base, target = threshold
            scored = (values(base) >= target).astype(int)
        elif stat in {"DD", "TD"}:
            categories = sum(
                (values(base) >= 10).astype(int)
                for base in ("PTS", "REB", "AST", "STL", "BLK")
            )
            scored = (categories >= (2 if stat == "DD" else 3)).astype(int)
        else:
            scored = values(stat)
        out["FP"] += scored * weight
    return out


def fantasy_points(row: pd.Series, weights: dict) -> float:
    return float(add_fantasy_points(pd.DataFrame([row]), weights).FP.iloc[0])
