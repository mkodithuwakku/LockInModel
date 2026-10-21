"""Season production for the current roster, not historical ownership/locked totals."""

import pandas as pd
from fetch_data import normalize_stats_for_scoring
from scoring import add_fantasy_points
from transport import DataUnavailable

STATS = (
    "PTS",
    "REB",
    "AST",
    "STL",
    "BLK",
    "FG3M",
    "TOV",
    "MIN",
    "FGM",
    "FGA",
    "FTM",
    "FTA",
)


def season_review(games, roster, weights, reference, unavailable=False, season=None):
    ref = pd.Timestamp(reference)
    year = (
        int(str(season)[:4])
        if season and str(season)[:4].isdigit()
        else ref.year - (ref.month < 10)
    )
    start = pd.Timestamp(year=year, month=10, day=1)
    end = min(ref, pd.Timestamp(year=year + 1, month=9, day=30))
    base = dict(
        season=f"{year}–{str(year+1)[-2:]}",
        as_of=str(end.date()),
        scope="current_roster",
        status="unavailable" if unavailable else "empty",
        roster_count=len(roster),
        covered_players=0,
        appearances=0,
        total_fp=None,
        fp_per_game=None,
        top_three_share=None,
        stats={},
        weeks=[],
        players=[],
    )
    if unavailable or games is None or games.empty:
        return base
    ids = {str(r["player_id"]) for r in roster if r.get("player_id")}
    frame = games[
        games.PLAYER_ID.astype(str).isin(ids) & games.GAME_DATE.between(start, end)
    ].copy()
    if frame.empty:
        return base
    frame["PLAYER_ID"] = frame.PLAYER_ID.astype(str)
    frame = frame.drop_duplicates(
        ["PLAYER_ID"] + (["GAME_ID"] if "GAME_ID" in frame else ["GAME_DATE"]),
        keep="last",
    )
    try:
        scored = (
            add_fantasy_points(normalize_stats_for_scoring(frame), weights)
            .sort_values("GAME_DATE")
            .reset_index(drop=True)
        )
    except (DataUnavailable, ValueError, KeyError, TypeError):
        return dict(base, status="unavailable")
    scored["PLAYER_ID"] = scored.PLAYER_ID.astype(str)
    groups = {pid: h for pid, h in scored.groupby("PLAYER_ID")}
    players = []
    seen = set()
    for row in roster:
        pid = str(row.get("player_id") or "")
        if not pid or pid in seen or pid not in groups:
            continue
        seen.add(pid)
        h = groups[pid]
        recent = h.tail(5).FP
        old = h.iloc[-10:-5].FP
        players.append(
            dict(
                player_id=pid,
                player=row["player"],
                games=len(h),
                total_fp=round(float(h.FP.sum()), 2),
                average_fp=round(float(h.FP.mean()), 2),
                recent_fp=round(float(recent.mean()), 2),
                recent_games=len(recent),
                change=(
                    round(float(recent.mean() - old.mean()), 2)
                    if len(h) >= 10
                    else None
                ),
                spread=round(float(h.FP.std(ddof=0)), 2) if len(h) >= 5 else None,
                best_fp=round(float(h.FP.max()), 2),
                best_date=str(h.loc[h.FP.idxmax(), "GAME_DATE"].date()),
                last_played=str(h.GAME_DATE.max().date()),
            )
        )
    players.sort(key=lambda p: (-p["total_fp"], p["player"]))
    positive = sum(max(0, p["total_fp"]) for p in players)
    for p in players:
        p["share"] = (
            round(max(0, p["total_fp"]) / positive * 100, 1) if positive else None
        )
    stats = {
        k: round(float(scored[k].sum()), 2)
        for k in STATS
        if k in scored
        and k not in scored.attrs.get("imputed_stats", [])
        and scored[k].notna().all()
    }
    stats["FG_PCT"] = (
        round(stats["FGM"] / stats["FGA"] * 100, 1)
        if stats.get("FGA", 0) > 0 and "FGM" in stats
        else None
    )
    stats["FT_PCT"] = (
        round(stats["FTM"] / stats["FTA"] * 100, 1)
        if stats.get("FTA", 0) > 0 and "FTM" in stats
        else None
    )
    weeks = []
    week = scored.GAME_DATE - pd.to_timedelta(scored.GAME_DATE.dt.weekday, unit="D")
    for day, h in scored.groupby(week):
        weeks.append(
            dict(
                date=str(day.date()),
                total_fp=round(float(h.FP.sum()), 2),
                average_fp=round(float(h.FP.mean()), 2),
                games=len(h),
            )
        )
    return dict(
        base,
        status="ready",
        covered_players=len(players),
        appearances=len(scored),
        total_fp=round(float(scored.FP.sum()), 2),
        fp_per_game=round(float(scored.FP.mean()), 2),
        top_three_share=(
            round(sum(max(0, p["total_fp"]) for p in players[:3]) / positive * 100, 1)
            if positive
            else None
        ),
        stats=stats,
        weeks=weeks,
        players=players,
    )
