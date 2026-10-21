"""Shared observed-history bootstrap for early-season forecasts and lock decisions."""

import pandas as pd
from fetch_data import normalize_stats_for_scoring
from scoring import add_fantasy_points
from transport import DataUnavailable


def blend_seasons(current, previous, weights, size, reference):
    """Fill a small current-season sample with real, latest historical games."""
    if previous is None or previous.empty or len(current) >= size:
        return None
    try:
        reference = pd.Timestamp(reference)
        boundary = pd.Timestamp(
            year=reference.year if reference.month >= 10 else reference.year - 1,
            month=10,
            day=1,
        )
        previous = previous[previous.GAME_DATE < min(reference, boundary)]
        if previous.empty:
            return None
        current = normalize_stats_for_scoring(current).sort_values("GAME_DATE")
        previous = (
            normalize_stats_for_scoring(previous)
            .sort_values("GAME_DATE")
            .tail(size - len(current))
        )
        history = pd.concat([previous, current], ignore_index=True).sort_values(
            "GAME_DATE"
        )
        # Preserve missing-stat evidence across frames from different providers.
        history.attrs["imputed_stats"] = sorted(
            set(current.attrs.get("imputed_stats", []))
            | set(previous.attrs.get("imputed_stats", []))
        )
        add_fantasy_points(
            history, weights
        )  # A bad prior must not erase valid current history.
        return history, len(current), len(previous)
    except (DataUnavailable, ValueError, KeyError, TypeError):
        return None
