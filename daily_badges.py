"""Small previous-night NBA leader badges, with optional league-scored categories."""

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
    "merchant": ("FTM",),
    "heartbreak": ("FG3A", "FG3M"),
    "shield": ("STL", "BLK"),
    "creator": ("AST", "TOV"),
    "magician": ("PTS", "REB", "AST", "STL", "BLK"),
    "coffee": ("PTS", "REB", "AST", "STL", "BLK"),
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
        if key in {"bricks", "heartbreak"}:
            scores = scores - values.iloc[:, 1]
            if (scores < 0).any():
                continue
        if key == "shield":
            # Stocks need at least one steal AND one block in the same game.
            scores = values.sum(axis=1).where((values >= 1).all(axis=1), 0)
        elif key == "creator":
            scores = (values.AST - values.TOV).where(values.AST >= 5, 0)
        elif key in {"magician", "coffee"}:
            threshold = 3 if key == "magician" else 2
            scores = ((values >= 10).sum(axis=1) >= threshold).astype(int)
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


FANTASY_CATEGORIES = ("overachiever", "underachiever", "efficient", "inefficient")


def fantasy_night_badges(games, reference, weights, forecasts=None):
    """Rank observed FP/min and signed errors against saved pregame forecasts."""
    from fetch_data import normalize_stats_for_scoring
    from scoring import add_fantasy_points
    from transport import DataUnavailable

    if games.empty or not {"PLAYER_ID", "GAME_DATE", "MIN"}.issubset(games):
        return {}
    day = dt.date.fromisoformat(str(reference)) - dt.timedelta(days=1)
    night = games[pd.to_datetime(games.GAME_DATE).dt.date == day].copy()
    if night.empty:
        return {}
    night = night.dropna(subset=["PLAYER_ID"])
    night["PLAYER_ID"] = night.PLAYER_ID.astype(str)
    night = night.drop_duplicates(
        ["PLAYER_ID"] + (["GAME_ID"] if "GAME_ID" in night else []), keep="last"
    )
    try:
        scored = add_fantasy_points(normalize_stats_for_scoring(night), weights)
    except (DataUnavailable, ValueError, KeyError, TypeError):
        return {}
    totals = scored.groupby("PLAYER_ID")[["FP", "MIN"]].sum()
    totals = totals[totals.MIN > 0]  # Zero-minute/DNP rows cannot earn rate badges.
    if totals.empty:
        return {}
    rates = totals.FP / totals.MIN
    projected = pd.Series(forecasts or {}, dtype=float).reindex(totals.index)
    projected = projected * scored.groupby("PLAYER_ID").size().reindex(totals.index)
    valid = np.isfinite(projected)
    delta = (totals.FP - projected)[valid]
    result = {}
    for key, values, ascending in (
        ("overachiever", delta[delta > 0], False),
        ("underachiever", -delta[delta < 0], False),
        ("efficient", rates, False),
        ("inefficient", rates, True),
    ):
        ranks = values.rank(method="min", ascending=ascending)
        for pid, rank in ranks[ranks <= 3].items():
            value = float(values[pid])
            award = dict(
                key=key,
                date=str(day),
                rank=int(rank),
                value=round(value, 3),
                tied=bool((values == value).sum() > 1),
                scope="league_nba",
            )
            if key in {"overachiever", "underachiever"}:
                award.update(
                    projected_fp=float(projected[pid]),
                    actual_fp=float(totals.loc[pid, "FP"]),
                    forecast_count=int(valid.sum()),
                    player_count=len(totals),
                )
            result.setdefault(pid, []).append(award)
    return result


def combine_badges(*groups):
    from badge_awards import EXTRA_KEYS

    order = list(CATEGORIES) + list(FANTASY_CATEGORIES) + EXTRA_KEYS
    return sorted(
        [b for group in groups for b in group],
        key=lambda b: (b["rank"], order.index(b["key"])),
    )
