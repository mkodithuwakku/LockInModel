"""Read-only Sleeper NBA import. Scoring gaps and ownership are explicit."""

import datetime as dt
from transport import HTTP, DataUnavailable
from storage import (
    ROOT,
    write_json,
    read_json,
    load_cfg,
    save_cfg,
    LOCK,
    organize_teams,
)
from fetch_data import canonical_name
from scoring import apply_scoring_policy

BASE = "https://api.sleeper.app/v1"
SCORING = {
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
    "dd": "DD",
    "td": "TD",
    "bonus_pt_40p": "PTS40",
    "bonus_pt_50p": "PTS50",
}


def get(path, ttl=900):
    return HTTP.get(BASE + path, ttl=ttl, pace=1)


def sync(username, season):
    if not isinstance(username, str) or not username.strip() or "/" in username:
        raise ValueError("Enter a Sleeper username.")
    if not str(season).isdigit() or len(str(season)) != 4:
        raise ValueError("Enter a four-digit season start year.")
    user = get("/user/" + username.strip(), 86400)
    if not user or not user.get("user_id"):
        raise DataUnavailable("Sleeper account not found.")
    uid = user["user_id"]
    leagues = get(f"/user/{uid}/leagues/nba/{season}")
    if not isinstance(leagues, list):
        raise DataUnavailable("Sleeper did not return a league list.")
    if not leagues:
        return {
            "count": 0,
            "message": f"No NBA leagues found for {season}. Existing teams kept.",
        }
    directory = get("/players/nba", 86400)
    if not isinstance(directory, dict) or not directory:
        raise DataUnavailable("Sleeper player directory unavailable.")
    write_json(ROOT / "state/sleeper-players.json", directory)
    imported = []
    for league in leagues:
        lid = league["league_id"]
        details = get("/league/" + lid)
        rosters = get("/league/" + lid + "/rosters")
        users = get("/league/" + lid + "/users")
        if not isinstance(rosters, list) or len(rosters) != int(
            details["total_rosters"]
        ):
            raise DataUnavailable(
                "Incomplete league rosters; previous import retained."
            )
        owner = next(
            (
                r
                for r in rosters
                if r.get("owner_id") == uid or uid in (r.get("co_owners") or [])
            ),
            None,
        )
        if owner is None:
            continue

        def names(ids):
            out = []
            for pid in ids:
                if str(pid) == "0":
                    continue
                p = directory.get(str(pid))
                if not p:
                    raise DataUnavailable("Sleeper roster has an unknown player ID.")
                out.append(
                    p.get("full_name") or (p["first_name"] + " " + p["last_name"])
                )
            return list(dict.fromkeys(out))

        player_ids = list(
            dict.fromkeys(
                (owner.get("players") or [])
                + (owner.get("reserve") or [])
                + (owner.get("taxi") or [])
            )
        )
        roster_names = names(player_ids)
        starters = names(owner.get("starters") or [])
        occupied = names(
            [
                pid
                for r in rosters
                for field in ["players", "reserve", "taxi"]
                for pid in (r.get(field) or [])
            ]
        )
        settings = details.get("scoring_settings")
        if not isinstance(settings, dict):
            raise DataUnavailable("League scoring rules unavailable.")
        unsupported = {k: v for k, v in settings.items() if k not in SCORING and v != 0}
        weights = {SCORING[k]: v for k, v in settings.items() if k in SCORING}
        profile = next((u for u in users if u.get("user_id") == uid), {})
        team_name = (
            (profile.get("metadata") or {}).get("team_name")
            or user.get("display_name")
            or username
        )
        imported.append(
            {
                "id": "sleeper-" + lid,
                "archived": False,
                "name": team_name,
                "league_name": details["name"].strip(),
                "league_id": lid,
                "season": str(season),
                "league_status": details.get("status"),
                "source": "sleeper",
                "players": roster_names,
                "starters": [n for n in starters if n in roster_names],
                "weights": weights,
                "unsupported_scoring": unsupported,
                "owned_players": occupied,
                "ownership_complete": True,
                "synced_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "sleeper_username": username,
                "player_meta": {
                    canonical_name(
                        directory[str(pid)].get("full_name")
                        or (
                            directory[str(pid)]["first_name"]
                            + " "
                            + directory[str(pid)]["last_name"]
                        )
                    ): {
                        "positions": directory[str(pid)].get("fantasy_positions", []),
                        "injury_status": directory[str(pid)].get("injury_status"),
                        "sleeper_id": str(pid),
                    }
                    for pid in player_ids
                },
            }
        )
    for team in imported:
        apply_scoring_policy(team)
    # Commit a complete import atomically; partial network failures don't erase rosters.
    with LOCK:
        cfg = load_cfg()
        incoming = {t["id"] for t in imported}
        for old in cfg["teams"]:
            if (
                old.get("source") == "sleeper"
                and old.get("sleeper_username", "").casefold() == username.casefold()
                and old.get("season") == str(season)
                and old["id"] not in incoming
            ):
                old.update(
                    archived=True, archive_reason="No longer in account league list"
                )
        cfg["teams"] = [t for t in cfg["teams"] if t["id"] not in incoming] + imported
        organize_teams(cfg)
        cfg["sleeper"] = {"username": username, "season": str(season)}
        save_cfg(cfg)
    return {
        "count": len(imported),
        "message": f"Imported {len(imported)} teams from Sleeper. Scoring coverage is shown per league.",
    }


def sync_current():
    """Discover this season, then refresh the last known season if none exists yet."""
    from engine import today

    settings = load_cfg().get("sleeper", {})
    if not settings.get("username"):
        return {"count": 0, "message": "Connect a Sleeper account first."}
    date = today()
    season = str(date.year if date.month >= 9 else date.year - 1)
    result = sync(settings["username"], season)
    if not result["count"] and season != settings.get("season"):
        return sync(settings["username"], settings["season"])
    return result
