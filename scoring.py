"""League-weighted fantasy scoring with explicit missing-value rejection."""

import math
import numpy as np
import pandas as pd


# User-approved exception: Sleeper flagrant-foul points do not enter our model.
IGNORED_LEAGUE_SCORING = {"ff"}


def apply_scoring_policy(team):
    """Record intentionally excluded rules separately from missing scoring data."""
    unsupported = dict(team.get("unsupported_scoring", {}))
    ignored = dict(team.get("ignored_scoring", {}))
    for key in IGNORED_LEAGUE_SCORING:
        if key in unsupported:
            ignored[key] = unsupported.pop(key)
    if ignored:
        team["ignored_scoring"] = ignored
        team["unsupported_scoring"] = unsupported
    return team


def fantasy_points(row: pd.Series, weights: dict) -> float:
    total = 0.0
    for stat, weight in weights.items():
        weight = float(weight)
        if not math.isfinite(weight):
            raise ValueError("Fantasy weights must be finite.")
        if weight == 0:
            continue
        if stat not in row or not math.isfinite(float(row[stat])):
            raise ValueError("Missing or invalid weighted stat: " + stat)
        total += float(row[stat]) * weight
    return total


def add_fantasy_points(df: pd.DataFrame, weights: dict) -> pd.DataFrame:
    out = df.copy()
    out["FP"] = 0.0
    imputed = set(df.attrs.get("imputed_stats", []))
    for stat, weight in weights.items():
        weight = float(weight)
        if not math.isfinite(weight):
            raise ValueError("Fantasy weights must be finite.")
        if weight == 0:
            continue
        if stat not in out or stat in imputed:
            raise ValueError("Missing weighted stat: " + stat)
        values = pd.to_numeric(out[stat], errors="coerce")
        if not np.isfinite(values).all():
            raise ValueError("Invalid weighted stat: " + stat)
        out["FP"] += values * weight
    return out
