# fetch_data.py

import os
import datetime as dt
from typing import List, Dict, Tuple
import pandas as pd

from nba_api.stats.endpoints import playergamelog, playercareerstats, playernextngames
from nba_api.stats.static import players

from logger import get_logger
log = get_logger(__name__)

"""
Utilities to fetch and prepare NBA player game logs.

- resolve_player_ids: name -> NBA ID
- get_player_logs: recent player logs with parsed dates
- get_week_bounds / filter_week_games / last_n_days
- normalize_stats_for_scoring
- get_career_per_game / compute_career_fp  (via PlayerCareerStats PerGame)
- estimate_remaining_games_this_week (via PlayerNextNGames)
"""

# ------------------------- helpers: season string ----------------------------

def _season_for_today(reference: dt.date = None) -> str:
    """
    Return NBA season string like '2025-26' for today's date (or reference).
    NBA season starts in October, so months >= 10 map to the season's start year.
    """
    today = reference or dt.date.today()
    start_year = today.year if today.month >= 10 else today.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


# ------------------------ resolve player IDs --------------------------------

def resolve_player_ids(names: List[str]) -> Dict[str, int]:
    """Resolve a list of player full names to their NBA player IDs."""
    log.debug(f"Resolving player IDs for {len(names)} names: {names}")

    all_players = players.get_active_players() + players.get_inactive_players()
    name_to_id = {}
    for n in names:
        match = next((p for p in all_players if p["full_name"].lower() == n.lower()), None)
        if not match:
            raise ValueError(f"Could not resolve NBA player: {n}")
        name_to_id[n] = match["id"]
        log.debug(f"Resolved: {name_to_id}")

    return name_to_id


# --------------------------- player logs ------------------------------------

def get_player_logs(player_id: int, season: str = None, last_n_days: int = 60) -> pd.DataFrame:
    """
    Fetch recent game logs for a player, parse GAME_DATE, and keep only the last_n_days.
    """
    # Infer season if not provided (format: 'YYYY-YY', e.g., '2025-26')
    if season is None:
        season = _season_for_today()

    log.debug(f"Fetching logs player_id={player_id}, season={season}, days={last_n_days}")

    ep = playergamelog.PlayerGameLog(
        player_id=player_id,
        season=season,
        season_type_all_star="Regular Season",
        timeout=12,
    )
    dfs = ep.get_data_frames()
    if not dfs or dfs[0].empty:
        log.debug("Fetched 0 rows from playergamelog")
        return pd.DataFrame()

    gl = dfs[0].copy()

    if "GAME_DATE" not in gl.columns:
        log.debug(f"Unexpected columns returned: {list(gl.columns)}")
        return pd.DataFrame()

    gl["GAME_DATE"] = pd.to_datetime(gl["GAME_DATE"], errors="coerce")
    gl = gl.dropna(subset=["GAME_DATE"])

    try:
        log.debug(f"Fetched {len(gl)} rows; date range {gl['GAME_DATE'].min().date()} .. {gl['GAME_DATE'].max().date()}")
    except Exception:
        log.debug(f"Fetched {len(gl)} rows; (date range not available)")

    cutoff = pd.Timestamp.today().normalize() - pd.Timedelta(days=last_n_days)
    gl = gl[gl["GAME_DATE"] >= cutoff].copy()

    log.debug(f"After cutoff({last_n_days}d): {len(gl)} rows")
    return gl


# --------------------------- week helpers -----------------------------------

def get_week_bounds(reference: dt.date = None) -> Tuple[pd.Timestamp, pd.Timestamp]:
    """Return the start (Monday) and end (Sunday) timestamps for the fantasy week."""
    today = reference or dt.date.today()
    monday = today - dt.timedelta(days=today.weekday())
    sunday = monday + dt.timedelta(days=6)

    log.debug(f"Week bounds {monday}..{sunday}")
    return pd.Timestamp(monday), pd.Timestamp(sunday)


def filter_week_games(df: pd.DataFrame, week_start: pd.Timestamp, week_end: pd.Timestamp) -> pd.DataFrame:
    """Filter game log DataFrame to rows within the given week bounds (inclusive)."""
    out = df[(df["GAME_DATE"] >= week_start) & (df["GAME_DATE"] <= week_end)].copy()
    log.debug(f"Week filter -> {len(out)} rows")
    return out


def last_n_days(df: pd.DataFrame, days: int) -> pd.DataFrame:
    """Return rows from the DataFrame for the last `days` days (inclusive)."""
    cutoff = pd.Timestamp.today().normalize() - pd.Timedelta(days=days)
    return df[df["GAME_DATE"] >= cutoff].copy()


# ------------------------ columns / scoring norm ----------------------------

# Base stats we expect to be present (add zeros if missing)
STAT_MAP = {
    "PTS": "PTS", "REB": "REB", "AST": "AST", "STL": "STL", "BLK": "BLK", "TOV": "TOV",
    "FG3M": "FG3M", "FGA": "FGA", "FGM": "FGM", "FTA": "FTA", "FTM": "FTM",
}

# Derived flags we compute here from common box score fields
DERIVED_FLAGS = ["DD", "TD", "PTS40", "PTS50"]

def _compute_derived_flags(df: pd.DataFrame) -> pd.DataFrame:
    """Add DD/TD/PTS40/PTS50 flags from boxscore stats."""
    for c in ["PTS", "REB", "AST", "STL", "BLK"]:
        if c not in df.columns:
            df[c] = 0

    cats = (df[["PTS", "REB", "AST", "STL", "BLK"]] >= 10).sum(axis=1)
    df["TD"] = (cats >= 3).astype(int)
    df["DD"] = (cats >= 2).astype(int)  # counts TD as well (typical fantasy rule)

    df["PTS40"] = (df["PTS"] >= 40).astype(int)
    df["PTS50"] = (df["PTS"] >= 50).astype(int)
    return df

def normalize_stats_for_scoring(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure required stat columns exist for scoring and return sorted subset.
    """
    log.debug(f"Normalizing columns; incoming columns: {list(df.columns)}")

    for c in STAT_MAP.values():
        if c not in df.columns:
            df[c] = 0

    df = _compute_derived_flags(df)

    for col in ["DD", "TD", "PTS40", "PTS50"]:
        if col not in df.columns:
            df[col] = 0

    keep = ["GAME_DATE", "MATCHUP", "WL", "MIN", "PLUS_MINUS"] + list(STAT_MAP.values())
    out = df[keep].copy()
    out.sort_values("GAME_DATE", inplace=True)

    log.debug("Normalization complete (added missing stats if any).")
    return out


# ------------------------ career per-game & FP prior ------------------------

def get_career_per_game(player_id: int) -> pd.Series:
    """
    Return a Series of **per-game** career regular-season stats via PlayerCareerStats.
    We request PerMode='PerGame' with LeagueID='00' so fields are already per-game.

    If no data (or GP==0), returns an empty Series.
    """
    try:
        pcs = playercareerstats.PlayerCareerStats(
            player_id=player_id,
            per_mode36="PerGame",    # PerMode per docs
            league_id_nullable="00", # NBA
            timeout=12,
        )
        df = pcs.career_totals_regular_season.get_data_frame()
        if df is None or df.empty:
            return pd.Series(dtype=float)

        row = df.iloc[0]
        gp = float(row.get("GP", 0) or 0)
        if gp <= 0:
            return pd.Series(dtype=float)

        # With PerMode=PerGame, these are already per-game values.
        per_game = {
            "PTS": float(row.get("PTS", 0) or 0.0),
            "REB": float(row.get("REB", 0) or 0.0),
            "AST": float(row.get("AST", 0) or 0.0),
            "STL": float(row.get("STL", 0) or 0.0),
            "BLK": float(row.get("BLK", 0) or 0.0),
            "TOV": float(row.get("TOV", 0) or 0.0),
            "FG3M": float(row.get("FG3M", 0) or 0.0),
            "FGA": float(row.get("FGA", 0) or 0.0),
            "FGM": float(row.get("FGM", 0) or 0.0),
            "FTA": float(row.get("FTA", 0) or 0.0),
            "FTM": float(row.get("FTM", 0) or 0.0),
            "MIN": float(row.get("MIN", 0) or 0.0),
        }
        return pd.Series(per_game, dtype=float)
    except Exception as e:
        log.warning(f"career per-game fetch failed for pid={player_id}: {e}")
        return pd.Series(dtype=float)


def compute_career_fp(player_id: int, weights: dict) -> float:
    """
    Compute career **per-game** fantasy points using your league weights.
    Returns np.nan if unavailable. If all career stats are 0 (rookie), returns 0.0
    so the caller can apply the rookie guard (17.5).
    """
    s = get_career_per_game(player_id)
    if s.empty:
        return float("nan")
    if float(s.fillna(0).abs().sum()) == 0.0:
        return 0.0

    fp = 0.0
    for k, w in weights.items():
        fp += float(s.get(k, 0.0)) * float(w or 0.0)

    fp_val = float(fp)
    log.debug(f"[career FP] pid={player_id} per-game FP={fp_val:.2f}")
    return fp_val


# ---------------------- PlayerNextNGames helpers -----------------------------

def get_player_next_games(
    player_id: int,
    season: str = None,
    season_type: str = "Regular Season",
    number_of_games: int = 30,
    league_id: str = "00",
) -> pd.DataFrame:
    """
    Fetch upcoming games for `player_id`. Tries the current season first; if empty,
    retries with Season='ALL' (some NBA endpoints behave this way early in the year).
    Returns a DataFrame with a parsed 'GAME_DATE' (datetime64) when available.
    """
    if season is None:
        season = _season_for_today()

    def _call(season_value: str) -> pd.DataFrame:
        ep = playernextngames.PlayerNextNGames(
            player_id=player_id,
            number_of_games=number_of_games,
            season_all=season_value,           # REQUIRED
            season_type_all_star=season_type,  # REQUIRED
            league_id_nullable=league_id,      # usually '00'
            timeout=15,
        )
        df = ep.next_n_games.get_data_frame()
        if df is None:
            return pd.DataFrame()
        # Normalize date column if present
        if "GAME_DATE" in df.columns:
            df = df.copy()
            df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"], errors="coerce")
            df = df.dropna(subset=["GAME_DATE"])
        return df

    # First try the current season (e.g., '2025-26')
    df = pd.DataFrame()
    try:
        df = _call(season)
    except Exception as e:
        log.debug(f"PlayerNextNGames season='{season}' failed for pid={player_id}: {e}")

    log.debug(
        f"PlayerNextNGames(pid={player_id}, season='{season}', season_type='{season_type}', "
        f"league='{league_id}') -> {0 if df is None else len(df)} rows"
    )

    # Fallback to ALL if empty
    if df is None or df.empty:
        try:
            df = _call("ALL")
            log.debug(f"PlayerNextNGames fallback season='ALL' -> {0 if df is None else len(df)} rows")
        except Exception as e:
            log.debug(f"PlayerNextNGames season='ALL' failed for pid={player_id}: {e}")
            return pd.DataFrame()

    # Optional debug dump of what the API returned
    dump_dir = os.getenv("DEBUG_DUMP_DIR")
    if dump_dir:
        try:
            os.makedirs(dump_dir, exist_ok=True)
            out_path = os.path.join(dump_dir, f"{player_id}_next_games.csv")
            (df if df is not None else pd.DataFrame()).to_csv(out_path, index=False)
        except Exception as e:
            log.debug(f"DEBUG_DUMP_DIR write failed for pid={player_id}: {e}")

    return df if df is not None else pd.DataFrame()


# ---------------------- remaining games this week ---------------------------

def estimate_remaining_games_this_week(
    player_id: int,
    last_game_date: pd.Timestamp,
    week_end: pd.Timestamp,
    lookahead: int = 30,
) -> int:
    """
    Estimate remaining games in the current week using PlayerNextNGames.

    We fetch the player's next N games for the current season (fallback 'ALL')
    and count those with GAME_DATE in (last_game_date, week_end]
    (strictly after the last played date, inclusive of week_end).
    """
    try:
        df = get_player_next_games(
            player_id=player_id,
            season=_season_for_today(),
            season_type="Regular Season",
            number_of_games=lookahead,
            league_id="00",
        )
    except Exception as e:
        log.debug(f"estimate_remaining_games_this_week: fetch failed for pid={player_id}: {e}")
        return 0

    if df is None or df.empty or "GAME_DATE" not in df.columns:
        return 0

    # Normalize window
    start = pd.to_datetime(last_game_date).normalize() + pd.Timedelta(days=1)
    end   = pd.to_datetime(week_end).normalize()

    mask = (df["GAME_DATE"] >= start) & (df["GAME_DATE"] <= end)
    count = int(mask.sum())

    log.debug(
        f"[estimate_remaining_games_this_week] pid={player_id} "
        f"window={start.date()}..{end.date()} -> remaining={count}"
    )
    if count > 0:
        dates = ", ".join(sorted({d.strftime("%Y-%m-%d") for d in df.loc[mask, "GAME_DATE"]}))
        log.debug(f"[estimate_remaining_games_this_week] upcoming dates: {dates}")

    return count
