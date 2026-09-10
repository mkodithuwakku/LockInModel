"""League-weighted fantasy scoring with explicit missing-value rejection."""

import math
import numpy as np
import pandas as pd


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
