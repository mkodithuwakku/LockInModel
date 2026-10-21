"""Per-game milestones and contextual awards, using observed season games only."""

import datetime as dt
import math

import numpy as np
import pandas as pd

MILESTONES = {
    "FG3M": (5, 10),
    "AST": (10, 15, 20),
    "REB": (10, 15, 20),
    "BLK": (10,),
    "STL": (10,),
    "PTS": (30, 40, 50, 60, 70),
}
EXTRA_KEYS = [
    f"milestone_{stat.lower()}_{n}" for stat, tiers in MILESTONES.items() for n in tiers
] + [
    "careless",
    "hot_streak",
    "cold_streak",
    "win_mvp",
    "loss_mvp",
    "win_low",
    "home_hero",
    "away_villain",
    "unc",
    "new_gen",
]


def award(result, pid, key, day, value, **details):
    result.setdefault(str(pid), []).append(
        dict(
            key=key,
            date=str(day),
            rank=1,
            value=round(float(value), 3),
            tied=False,
            **details,
        )
    )


def ranked(result, key, values, day, ascending=False, places=1, **details):
    values = values[np.isfinite(values)]
    ranks = values.rank(method="min", ascending=ascending)
    for pid, rank in ranks[ranks <= places].items():
        award(result, pid, key, day, values[pid], **details)
        result[str(pid)][-1].update(
            rank=int(rank), tied=bool((values == values[pid]).sum() > 1)
        )


def observed_season(games, reference):
    """Deduplicate corrections, exclude future and previous-season observations."""
    if games.empty or not {"PLAYER_ID", "GAME_DATE", "MIN"}.issubset(games):
        return pd.DataFrame()
    day = dt.date.fromisoformat(str(reference)) - dt.timedelta(days=1)
    start = dt.date(day.year if day.month >= 10 else day.year - 1, 10, 1)
    frame = games.copy()
    frame["GAME_DATE"] = pd.to_datetime(frame.GAME_DATE, errors="coerce")
    frame = frame[frame.GAME_DATE.dt.date.between(start, day)].dropna(
        subset=["PLAYER_ID"]
    )
    frame["PLAYER_ID"] = frame.PLAYER_ID.astype(str)
    unique = (
        ["PLAYER_ID", "GAME_ID"] if "GAME_ID" in frame else ["PLAYER_ID", "GAME_DATE"]
    )
    frame = frame.drop_duplicates(unique, keep="last")
    minutes = pd.to_numeric(frame.MIN, errors="coerce")
    return frame[np.isfinite(minutes) & (minutes > 0)].copy()


def raw_awards(games, reference):
    frame = observed_season(games, reference)
    if frame.empty:
        return {}
    day = dt.date.fromisoformat(str(reference)) - dt.timedelta(days=1)
    night = frame[frame.GAME_DATE.dt.date == day]
    imputed = set(games.attrs.get("imputed_stats", []))
    result = {}
    for stat, tiers in MILESTONES.items():
        if stat not in night or stat in imputed:
            continue
        values = pd.to_numeric(night[stat], errors="coerce")
        if not np.isfinite(values).all() or (values < 0).any():
            continue
        # Highest single-game tier only; two small games cannot create a milestone.
        for pid, value in values.groupby(night.PLAYER_ID).max().items():
            reached = [n for n in tiers if value >= n]
            if reached:
                award(
                    result,
                    pid,
                    f"milestone_{stat.lower()}_{max(reached)}",
                    day,
                    value,
                    kind="milestone",
                )
    if {"AST", "TOV"}.issubset(night) and not {"AST", "TOV"} & imputed:
        values = night[["AST", "TOV"]].apply(pd.to_numeric, errors="coerce")
        if np.isfinite(values.to_numpy()).all() and not (values < 0).any().any():
            margin = (values.AST - values.TOV).groupby(night.PLAYER_ID).sum()
            ranked(result, "careless", margin, day, ascending=True, places=3)
    return result


def game_context(frame, calendar):
    """Prefer confirmed schedule results; NBA WL/MATCHUP support replay/fallback."""
    matches = {}
    for game in calendar or []:
        if game.get("status") not in {"complete", "final", "post_game"}:
            continue
        for side in ("home", "away"):
            matches.setdefault((game["date"], game[side]), []).append(game)
    contexts = []
    for _, row in frame.iterrows():
        matchup = str(row.get("MATCHUP", ""))
        home = True if " vs. " in matchup else False if " @ " in matchup else None
        outcome = row.get("WL") if row.get("WL") in {"W", "L"} else None
        found = matches.get(
            (str(row.GAME_DATE.date()), row.get("TEAM_ABBREVIATION")), []
        )
        exact = [g for g in found if str(g["game_id"]) == str(row.get("GAME_ID"))]
        game = exact[0] if len(exact) == 1 else found[0] if len(found) == 1 else None
        if game:
            home = row.get("TEAM_ABBREVIATION") == game["home"]
            a, b = game.get("home_points"), game.get("away_points")
            if (
                all(
                    isinstance(x, (int, float)) and math.isfinite(x) and x >= 0
                    for x in (a, b)
                )
                and a != b
            ):
                outcome = "W" if (a > b) == home else "L"
        contexts.append((home, outcome))
    return contexts


def fantasy_awards(games, reference, weights, calendar=None, birthdays=None):
    from fetch_data import normalize_stats_for_scoring
    from scoring import add_fantasy_points
    from transport import DataUnavailable

    frame = observed_season(games, reference)
    if frame.empty:
        return {}
    try:
        frame = add_fantasy_points(normalize_stats_for_scoring(frame), weights)
    except (DataUnavailable, ValueError, KeyError, TypeError):
        return {}
    day = dt.date.fromisoformat(str(reference)) - dt.timedelta(days=1)
    night = frame[frame.GAME_DATE.dt.date == day].copy()
    if night.empty:
        return {}
    context = game_context(night, calendar)
    night["home"] = [x[0] for x in context]
    night["outcome"] = [x[1] for x in context]
    ages = []
    for pid in night.PLAYER_ID:
        try:
            birth = dt.date.fromisoformat(str((birthdays or {}).get(pid)))
            age = (
                day.year
                - birth.year
                - ((day.month, day.day) < (birth.month, birth.day))
            )
            ages.append(age if 16 <= age <= 60 else np.nan)
        except (ValueError, TypeError):
            ages.append(np.nan)
    night["age"] = ages
    result = {}
    for key, mask, ascending in (
        ("win_mvp", night.outcome == "W", False),
        ("loss_mvp", night.outcome == "L", False),
        ("win_low", (night.outcome == "W") & (night.FP != 0), True),
        ("home_hero", night.home == True, False),
        ("away_villain", night.home == False, False),
        ("unc", night.age >= 32, False),
        ("new_gen", night.age <= 23, False),
    ):
        # These are single-game awards, including ties for first.
        selected = night[mask].groupby("PLAYER_ID").FP
        values = selected.min() if ascending else selected.max()
        ranked(result, key, values, day, ascending=ascending, scope="league_nba")
    played_last_night = set(night.PLAYER_ID)
    for pid, history in frame.groupby("PLAYER_ID"):
        if pid not in played_last_night or len(history) < 4:
            continue
        history = history.sort_values(
            ["GAME_DATE"] + (["GAME_ID"] if "GAME_ID" in history else [])
        )
        baseline = history.FP.mean()
        last = history.FP.tail(3)
        key = (
            "hot_streak"
            if (last > baseline).all()
            else "cold_streak" if (last < baseline).all() else None
        )
        if key:
            award(
                result,
                pid,
                key,
                day,
                3,
                kind="streak",
                scope="league_nba",
                season_average=float(baseline),
            )
    return result
