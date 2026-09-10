"""Resumable historical capture from an immutable archive of NBA API responses."""

import argparse
import hashlib
import random
import requests
import pandas as pd
from storage import ROOT, write_json, atomic_write
from fetch_data import normalize_stats_for_scoring, parse_dates

REPO = "llimllib/nba_data"
RENAME = {
    "gameId": "GAME_ID",
    "teamId": "TEAM_ID",
    "teamTricode": "TEAM_ABBREVIATION",
    "personId": "PLAYER_ID",
    "minutes": "MIN",
    "fieldGoalsMade": "FGM",
    "fieldGoalsAttempted": "FGA",
    "threePointersMade": "FG3M",
    "freeThrowsMade": "FTM",
    "freeThrowsAttempted": "FTA",
    "reboundsTotal": "REB",
    "assists": "AST",
    "steals": "STL",
    "blocks": "BLK",
    "turnovers": "TOV",
    "points": "PTS",
    "plusMinusPoints": "PLUS_MINUS",
    "position": "POSITION",
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def archive_file(directory, commit, file):
    target = directory / file
    if not target.exists():
        url = f"https://raw.githubusercontent.com/{REPO}/{commit}/data/{file}"
        response = requests.get(url, timeout=(5, 45))
        response.raise_for_status()
        temp = target.with_suffix(".part")
        temp.write_bytes(response.content)
        pd.read_parquet(temp)  # reject truncated or non-parquet responses
        temp.replace(target)
    return pd.read_parquet(target)


def transform(players, teams, season_start):
    teams = teams.rename(columns=str.upper)
    teams["GAME_ID"] = teams.GAME_ID.astype(str).str.zfill(10)
    teams = teams[teams.GAME_ID.str.startswith("002" + str(season_start)[-2:])].copy()
    teams = parse_dates(teams).drop_duplicates(["GAME_ID", "TEAM_ID"])
    if teams.groupby("GAME_ID").size().ne(2).any():
        raise ValueError("Incomplete team-game pairs.")
    p = players.rename(columns=RENAME).copy()
    p["GAME_ID"] = p.GAME_ID.astype(str).str.zfill(10)
    p = p[p.GAME_ID.isin(teams.GAME_ID)].copy()
    # DNP rows do not represent observed performances.
    p = p[
        p.MIN.notna() & ~p.MIN.astype(str).isin(["", "0:00", "00:00", "0", "0.0"])
    ].copy()
    p["PLAYER_NAME"] = p.firstName.fillna("") + " " + p.familyName.fillna("")
    p = p.merge(
        teams[["GAME_ID", "TEAM_ID", "GAME_DATE", "MATCHUP", "WL"]],
        on=["GAME_ID", "TEAM_ID"],
        how="left",
        validate="many_to_one",
    )
    p = normalize_stats_for_scoring(p)
    if p.duplicated(["PLAYER_ID", "GAME_ID"]).any():
        raise ValueError("Duplicate player-game records.")
    keep = [
        "GAME_ID",
        "GAME_DATE",
        "TEAM_ID",
        "TEAM_ABBREVIATION",
        "PLAYER_ID",
        "PLAYER_NAME",
        "POSITION",
        "MATCHUP",
        "WL",
        "MIN",
        "PTS",
        "REB",
        "AST",
        "STL",
        "BLK",
        "TOV",
        "FG3M",
        "FGM",
        "FGA",
        "FTM",
        "FTA",
        "PLUS_MINUS",
        "DD",
        "TD",
        "PTS40",
        "PTS50",
    ]
    return (
        p[keep],
        teams[["GAME_ID", "TEAM_ID", "GAME_DATE", "TEAM_ABBREVIATION", "MATCHUP"]],
    )


def capture(seed=202526):
    raw = ROOT / "data/cache/archive"
    raw.mkdir(parents=True, exist_ok=True)
    revision = raw / "commit.txt"
    if not revision.exists():
        r = requests.get(
            f"https://api.github.com/repos/{REPO}/commits/main", timeout=(5, 20)
        )
        r.raise_for_status()
        atomic_write(revision, r.json()["sha"])
    commit = revision.read_text().strip()
    files = {}
    for season in (2026, 2025):
        for kind in ("playerlog", "gamelog"):
            file = f"{kind}_{season}.parquet"
            files[file] = archive_file(raw, commit, file)
    games, schedule = transform(
        files["playerlog_2026.parquet"], files["gamelog_2026.parquet"], 2025
    )
    priors, _ = transform(
        files["playerlog_2025.parquet"], files["gamelog_2025.parquet"], 2024
    )
    eligible = []
    for monday in pd.date_range("2025-11-17", "2026-02-02", freq="W-MON"):
        week = schedule[
            schedule.GAME_DATE.between(monday, monday + pd.Timedelta(days=6))
        ]
        if week.TEAM_ID.nunique() == 30 and set(week.GAME_ID) <= set(games.GAME_ID):
            eligible.append(str(monday.date()))
    if not eligible:
        raise ValueError("No complete representative week found.")
    start = random.Random(seed).choice(eligible)
    end = str((pd.Timestamp(start) + pd.Timedelta(days=6)).date())
    directory = ROOT / "data/fixtures/2025-26"
    directory.mkdir(parents=True, exist_ok=True)
    for name, frame in [("games", games), ("schedule", schedule), ("priors", priors)]:
        temp = directory / (name + ".tmp.parquet")
        frame.to_parquet(temp, index=False)
        temp.replace(directory / (name + ".parquet"))
    manifest = {
        "schema_version": 1,
        "season": "2025-26",
        "week_start": start,
        "week_end": end,
        "default_date": str((pd.Timestamp(start) + pd.Timedelta(days=3)).date()),
        "seed": seed,
        "eligible_weeks": eligible,
        "source": f"https://github.com/{REPO}/tree/{commit}",
        "captured_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "source_files": {n: sha(raw / n) for n in files},
        "files": {
            n + ".parquet": sha(directory / (n + ".parquet"))
            for n in ["games", "schedule", "priors"]
        },
        "player_game_rows": len(games),
        "players": int(games.PLAYER_ID.nunique()),
        "team_game_rows": len(schedule),
        "games": int(schedule.GAME_ID.nunique()),
        "history_start": str(games.GAME_DATE.min().date()),
        "history_end": str(games.GAME_DATE.max().date()),
        "prior_policy": "2024-25 regular-season game average, not career average; rookies have no prior",
        "schedule_policy": "Finalized historical team schedule; not an as-known-at-the-time archive",
        "decision_time": "End of selected league day",
        "ownership_policy": "Current Sleeper roster snapshot or configured sample roster; historical ownership is unknown",
    }
    write_json(directory / "manifest.json", manifest)
    write_json(ROOT / "data/fixture-manifest.json", manifest)
    print(
        f"Captured {len(games):,} player-game rows, {manifest['players']} players. Test week {start} through {end}. Replay uses no NBA requests."
    )
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=202526)
    capture(parser.parse_args().seed)
