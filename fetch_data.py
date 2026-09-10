"""NBA adapters and strict scoring normalization; failures never mean zero games."""

import datetime as dt
import math
import unicodedata
import numpy as np
import pandas as pd
from nba_api.stats.endpoints import (
    playergamelog,
    playercareerstats,
    playernextngames,
    playergamelogs,
    leaguegamelog,
)
from nba_api.stats.static import players
from transport import HTTP, DataUnavailable

STAT_MAP = {
    s: s
    for s in [
        "PTS",
        "REB",
        "AST",
        "STL",
        "BLK",
        "TOV",
        "FG3M",
        "FGA",
        "FGM",
        "FTA",
        "FTM",
    ]
}
DERIVED_FLAGS = ["DD", "TD", "PTS40", "PTS50"]
CORE = ["PTS", "REB", "AST", "STL", "BLK", "TOV", "FG3M"]


def _season_for_today(reference=None):
    today = reference or dt.date.today()
    year = today.year if today.month >= 10 else today.year - 1
    return f"{year}-{str(year+1)[-2:]}"


def canonical_name(name):
    return (
        "".join(
            c
            for c in unicodedata.normalize("NFKD", name)
            if not unicodedata.combining(c)
        )
        .casefold()
        .strip()
    )


def resolve_player_ids(names):
    directory = {canonical_name(p["full_name"]): p["id"] for p in players.get_players()}
    result = {}
    for name in names:
        key = canonical_name(name)
        if key not in directory:
            raise ValueError("Could not resolve NBA player: " + name)
        result[name] = directory[key]
    return result


def endpoint_frame(endpoint, name=None, ttl=3600):
    data = HTTP.get(
        "https://stats.nba.com/stats/" + endpoint.endpoint,
        endpoint.parameters,
        ttl=ttl,
        pace=3,
    )
    sets = data.get("resultSets", data.get("resultSet"))
    if isinstance(sets, dict):
        sets = [sets]
    if not isinstance(sets, list) or not sets:
        raise DataUnavailable("NBA returned an unexpected table format.")
    table = next((s for s in sets if s.get("name") == name), None) if name else sets[0]
    if (
        not table
        or not isinstance(table.get("headers"), list)
        or not isinstance(table.get("rowSet"), list)
    ):
        raise DataUnavailable("NBA response is missing the requested table.")
    try:
        return pd.DataFrame(table["rowSet"], columns=table["headers"])
    except (ValueError, TypeError) as exc:
        raise DataUnavailable("NBA table has inconsistent rows.") from exc


def parse_dates(df):
    if "GAME_DATE" not in df:
        raise DataUnavailable("Game data is missing dates.")
    out = df.copy()
    out["GAME_DATE"] = pd.to_datetime(out["GAME_DATE"], errors="coerce", format="mixed")
    if out["GAME_DATE"].isna().any():
        raise DataUnavailable("Game data contains invalid dates.")
    return out.sort_values("GAME_DATE")


def get_player_logs(player_id, season=None, last_n_days=60, reference=None):
    ep = playergamelog.PlayerGameLog(
        player_id=player_id,
        season=season or _season_for_today(reference),
        season_type_all_star="Regular Season",
        get_request=False,
    )
    frame = endpoint_frame(ep)
    return last_days(parse_dates(frame), last_n_days, reference)


def get_week_bounds(reference=None):
    day = pd.Timestamp(reference or dt.date.today()).normalize()
    start = day - pd.Timedelta(days=day.weekday())
    return start, start + pd.Timedelta(days=6)


def filter_week_games(df, week_start, week_end):
    return df[df.GAME_DATE.between(week_start, week_end)].copy()


def last_days(df, days, reference=None):
    end = (
        pd.Timestamp(reference or dt.date.today()).normalize()
        + pd.Timedelta(days=1)
        - pd.Timedelta(microseconds=1)
    )
    start = end.normalize() - pd.Timedelta(days=days)
    return df[df.GAME_DATE.between(start, end)].copy()


last_n_days = last_days


def _compute_derived_flags(df):
    cats = (df[["PTS", "REB", "AST", "STL", "BLK"]] >= 10).sum(axis=1)
    df["DD"] = (cats >= 2).astype(int)
    df["TD"] = (cats >= 3).astype(int)
    df["PTS40"] = (df.PTS >= 40).astype(int)
    df["PTS50"] = (df.PTS >= 50).astype(int)
    return df


def normalize_stats_for_scoring(df):
    out = parse_dates(df)
    missing = set(CORE) - set(out.columns)
    if missing:
        raise DataUnavailable(
            "Box scores missing required stats: " + ", ".join(sorted(missing))
        )
    out.attrs["imputed_stats"] = list(
        set(out.attrs.get("imputed_stats", [])) | (set(STAT_MAP) - set(out.columns))
    )
    for field in STAT_MAP:
        if field not in out:
            out[field] = 0
        out[field] = pd.to_numeric(out[field], errors="coerce")
        if not np.isfinite(out[field]).all() or (out[field] < 0).any():
            raise DataUnavailable("Invalid box-score values for " + field)
    if "MIN" in out:

        def minutes(value):
            if isinstance(value, str) and ":" in value:
                parts = value.split(":")
                return float(parts[0]) + float(parts[1]) / 60
            return float(value)

        try:
            out["MIN"] = out["MIN"].map(minutes)
        except (ValueError, TypeError):
            raise DataUnavailable("Invalid playing-time data.")
        if not np.isfinite(out["MIN"]).all() or (out.MIN < 0).any():
            raise DataUnavailable("Invalid playing-time data.")
    for field in ["MATCHUP", "WL"]:
        if field not in out:
            out[field] = ""
    if "PLUS_MINUS" not in out:
        out["PLUS_MINUS"] = 0
    # Preserve identifiers, metadata, and derived flags for every downstream consumer.
    return _compute_derived_flags(out)


def get_career_per_game(player_id):
    ep = playercareerstats.PlayerCareerStats(
        player_id=player_id,
        per_mode36="PerGame",
        league_id_nullable="00",
        get_request=False,
    )
    frame = endpoint_frame(ep, "CareerTotalsRegularSeason", ttl=86400)
    if frame.empty or float(frame.iloc[0].get("GP", 0)) <= 0:
        raise DataUnavailable("Career history is unavailable.")
    return frame.iloc[0]


def compute_career_fp(player_id, weights):
    row = get_career_per_game(player_id)
    value = sum(
        float(row.get(k, 0)) * float(w) for k, w in weights.items() if k in STAT_MAP
    )
    if not math.isfinite(value):
        raise DataUnavailable("Career history is invalid.")
    return value


def get_player_next_games(
    player_id,
    season=None,
    season_type="Regular Season",
    number_of_games=30,
    league_id="00",
):
    ep = playernextngames.PlayerNextNGames(
        player_id=player_id,
        number_of_games=number_of_games,
        season_all=season or _season_for_today(),
        season_type_all_star=season_type,
        league_id_nullable=league_id,
        get_request=False,
    )
    return parse_dates(endpoint_frame(ep, ttl=1800))


def estimate_remaining_games_this_week(
    player_id, last_game_date, week_end, lookahead=30
):
    frame = get_player_next_games(player_id, number_of_games=lookahead)
    # Empty upcoming lists can mean provider trouble; only a populated validated
    # schedule lets this adapter assert a true zero within the fantasy week.
    if frame.empty:
        raise DataUnavailable(
            "Upcoming schedule is empty. Remaining games cannot be confirmed."
        )
    return int(
        (
            (frame.GAME_DATE > pd.Timestamp(last_game_date).normalize())
            & (frame.GAME_DATE <= week_end)
        ).sum()
    )


def bulk_player_logs(season):
    ep = playergamelogs.PlayerGameLogs(
        season_nullable=season, season_type_nullable="Regular Season", get_request=False
    )
    return parse_dates(endpoint_frame(ep, ttl=86400))


def bulk_team_logs(season):
    ep = leaguegamelog.LeagueGameLog(
        season=season,
        player_or_team_abbreviation="T",
        season_type_all_star="Regular Season",
        get_request=False,
    )
    return parse_dates(endpoint_frame(ep, ttl=86400))
