"""Small previous-night leader badges, independent of fantasy league scoring."""

import datetime as dt
import numpy as np
import pandas as pd

# Extending the feature means adding a stat here and its display label in insights.js.
CATEGORIES = {
    "sniper": ("FG3M",),
    "fire": ("FGM",),
    "boards": ("REB",),
    "bricks": ("FGA", "FGM"),
    "thief": ("STL",),
    "rejection": ("BLK",),
    "runner": ("MIN",),
    "dime": ("AST",),
    "sandwich": ("TOV",),
}


def previous_night_badges(games, reference):
    """Rank all observed NBA players, including ties in the first three places.

    Never backfill a quiet night from an older date. Missing/invalid category data
    suppresses that category instead of treating absent measurements as zero.
    """
    if games.empty or not {"PLAYER_ID", "GAME_DATE"}.issubset(games.columns):
        return {}
    day = dt.date.fromisoformat(str(reference)) - dt.timedelta(days=1)
    dates = pd.to_datetime(games.GAME_DATE, errors="coerce")
    night = games.loc[dates.dt.date == day].copy()
    if night.empty:
        return {}
    night = night.dropna(subset=["PLAYER_ID"])
    night["PLAYER_ID"] = night.PLAYER_ID.astype(str)
    unique = ["PLAYER_ID"] + (["GAME_ID"] if "GAME_ID" in night else [])
    night = night.drop_duplicates(unique, keep="last")
    result = {}
    imputed = set(games.attrs.get("imputed_stats", []))
    for key, fields in CATEGORIES.items():
        if not set(fields).issubset(night.columns) or set(fields) & imputed:
            continue
        values = night[list(fields)].apply(pd.to_numeric, errors="coerce")
        if not np.isfinite(values.to_numpy()).all() or (values < 0).any().any():
            continue
        scores = values.iloc[:, 0]
        if key == "bricks":
            scores = scores - values.iloc[:, 1]
            if (scores < 0).any():
                continue
        totals = scores.groupby(night.PLAYER_ID).sum()
        totals = totals[totals > 0]
        ranks = totals.rank(method="min", ascending=False)
        for pid, rank in ranks[ranks <= 3].items():
            value = float(totals[pid])
            result.setdefault(pid, []).append(
                {
                    "key": key,
                    "date": str(day),
                    "rank": int(rank),
                    "value": round(value, 2),
                    "tied": bool((totals == value).sum() > 1),
                }
            )
    for awards in result.values():
        awards.sort(key=lambda b: (b["rank"], list(CATEGORIES).index(b["key"])))
    return result
