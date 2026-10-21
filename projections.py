"""Validated Sleeper per-game forecasts, kept separate from observed game logs."""

import datetime as dt
import itertools
import math

import pandas as pd

from scoring import effective_weights, milestone
from transport import HTTP, DataUnavailable

STATS = {
    "pts": "PTS",
    "reb": "REB",
    "ast": "AST",
    "stl": "STL",
    "blk": "BLK",
    "to": "TOV",
    "tpm": "FG3M",
    "fgm": "FGM",
    "fga": "FGA",
    "ftm": "FTM",
    "fta": "FTA",
    "oreb": "OREB",
    "dreb": "DREB",
    "pf": "PF",
}
CORE = {"PTS", "REB", "AST", "STL", "BLK", "TOV", "FG3M", "MIN"}


def fetch_forecasts(season):
    payload = HTTP.get(
        f"https://api.sleeper.com/projections/nba/{season}",
        {"season_type": "regular", "grouping": "season"},
        ttl=21600,
        pace=1,
    )
    return parse_forecasts(payload, season)


def parse_forecasts(payload, season):
    if not isinstance(payload, list):
        raise DataUnavailable("Sleeper projections returned an invalid response.")
    result = {}
    for record in payload:
        if (
            not isinstance(record, dict)
            or record.get("category") != "proj"
            or record.get("company") != "rotowire"
            or str(record.get("season")) != str(season)
            or record.get("season_type") != "regular"
            or record.get("game_id") != "season"
        ):
            continue
        try:
            raw = record["stats"]
            games = float(raw["gp"])
            if not math.isfinite(games) or games <= 0:
                continue
            stats = {
                name: float(raw[key]) / games
                for key, name in STATS.items()
                if key in raw
            }
            if "sp" in raw:
                stats["MIN"] = float(raw["sp"]) / games / 60
            if "OREB" not in stats and "DREB" in stats and "REB" in stats:
                stats["OREB"] = stats["REB"] - stats["DREB"]
            if not CORE.issubset(stats) or not all(
                math.isfinite(v) and v >= 0 for v in stats.values()
            ):
                continue
            bonuses = {
                key.upper(): float(raw[key]) / games
                for key in ("dd", "td")
                if key in raw
            }
            if not all(math.isfinite(v) and 0 <= v <= 1 for v in bonuses.values()):
                continue
            updated = dt.datetime.fromtimestamp(
                float(record["updated_at"]) / 1000, dt.timezone.utc
            ).isoformat()
            result[str(record["player_id"])] = {
                "stats": stats,
                "bonuses": bonuses,
                "updated_at": updated,
            }
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            continue
    if not result:
        raise DataUnavailable("No valid current-season Sleeper projections available.")
    return result


def poisson_tail(mean, threshold):
    """Explicit approximation for bonus frequencies absent from the forecast feed."""
    if mean <= 0:
        return 0.0
    term = math.exp(-mean)
    cumulative = term
    for k in range(1, threshold):
        term *= mean / k
        cumulative += term
    return min(1.0, max(0.0, 1 - cumulative))


def forecast_profile(forecast, weights, reference):
    stats = forecast["stats"]
    adjusted, notes = effective_weights(pd.DataFrame([stats]), weights)
    estimated = False
    total = 0.0
    for stat, weight in adjusted.items():
        if not weight:
            continue
        threshold = milestone(stat)
        if threshold:
            base, target = threshold
            value = poisson_tail(stats[base], target)
            estimated = True
        elif stat in ("DD", "TD"):
            if stat in forecast["bonuses"]:
                value = forecast["bonuses"][stat]
            else:
                probabilities = [
                    poisson_tail(stats[k], 10)
                    for k in ("PTS", "REB", "AST", "STL", "BLK")
                ]
                value = sum(
                    math.prod(
                        p if hit else 1 - p for p, hit in zip(probabilities, hits)
                    )
                    for hits in itertools.product((False, True), repeat=5)
                    if sum(hits) >= (2 if stat == "DD" else 3)
                )
                estimated = True
        else:
            if stat not in stats:
                raise ValueError("Missing projected stat: " + stat)
            value = stats[stat]
        total += value * weight
    if estimated:
        notes.append(
            "Unprovided milestone frequencies use Poisson estimates from projected averages; multi-category bonuses assume independence."
        )
    return {
        "projected_fp": round(total, 2),
        "projected_stats": {k: round(v, 2) for k, v in stats.items()},
        "projection_source": "sleeper_rotowire",
        "sample_size": None,
        "last_played": None,
        "as_of": str(reference),
        "source_updated_at": forecast["updated_at"],
        "scoring_notes": notes,
    }
