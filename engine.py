"""Shared dashboard/report analysis; no delivery side effects."""

import datetime as dt
import pandas as pd
from zoneinfo import ZoneInfo
from nba_api.stats.static import players
from storage import ROOT, load_cfg, read_json, write_json
from providers import FixtureProvider, LiveProvider
from fetch_data import canonical_name, parse_dates
from decide import per_player_week_decision
from pickups import find_pickups
from transport import DataUnavailable


def today():
    return dt.datetime.now(ZoneInfo("America/Edmonton")).date()


def build_dashboard(
    mode="replay", reference=None, provider=None, cfg=None, phase="night"
):
    cfg = cfg or load_cfg()
    if mode == "live":
        cfg = dict(cfg, teams=[t for t in cfg["teams"] if not t.get("archived")])
        synced = [t for t in cfg["teams"] if t.get("source") == "sleeper"]
        if synced:
            cfg = dict(cfg, teams=synced)
        if not any(
            t.get("league_status", "in_season") == "in_season" for t in cfg["teams"]
        ):
            return roster_dashboard(cfg)
    provider = provider or (
        FixtureProvider() if mode == "replay" else LiveProvider(today())
    )
    reference = dt.date.fromisoformat(
        str(
            reference
            or (provider.manifest["default_date"] if mode == "replay" else today())
        )
    )
    if (
        mode == "replay"
        and not provider.manifest["week_start"]
        <= str(reference)
        <= provider.manifest["week_end"]
    ):
        raise ValueError("Choose a date inside the captured test week.")
    games = parse_dates(provider.games)
    cutoff = (
        pd.Timestamp(reference)
        if mode == "replay" and phase == "night"
        else pd.Timestamp(reference) - pd.Timedelta(days=1)
    )
    observed = games[games.GAME_DATE <= cutoff]
    if mode == "replay":
        provider.include_today = phase == "morning"
    # Player directory identity may use all rows; every statistical input uses observations only.
    identity = {
        canonical_name(str(r.PLAYER_NAME)): str(r.PLAYER_ID)
        for _, r in games[["PLAYER_ID", "PLAYER_NAME"]].drop_duplicates().iterrows()
    }
    identity.update(
        {
            canonical_name(p["full_name"]): str(p["id"])
            for p in players.get_players()
            if canonical_name(p["full_name"]) not in identity
        }
    )
    sleeper_players = read_json(ROOT / "state/sleeper-players.json", {})
    positions = {
        canonical_name(
            p.get("full_name")
            or (p.get("first_name", "") + " " + p.get("last_name", ""))
        ): p.get("fantasy_positions", [])
        for p in sleeper_players.values()
    }
    results = []
    alerts = []
    decision_cache = {}
    for team in cfg["teams"]:
        if mode == "live" and team.get("league_status", "in_season") != "in_season":
            continue
        weights = team.get("weights") or cfg["weights"]
        rows = []
        if team.get("unsupported_scoring"):
            alerts.append(
                {
                    "severity": "warning",
                    "team": team["name"],
                    "message": "League scoring includes unavailable stats: "
                    + ", ".join(team["unsupported_scoring"])
                    + ". Lock decisions withheld; displayed FP are partial estimates.",
                }
            )
        for name in team["players"]:
            pid = identity.get(canonical_name(name))
            if pid is None:
                row = {
                    "player": name,
                    "status": "UNRESOLVED",
                    "decision": None,
                    "note": "Player could not be matched to NBA data.",
                }
            else:
                key = (pid, tuple(sorted(weights.items())))
                if key not in decision_cache:
                    history = observed[observed.PLAYER_ID.astype(str) == pid]
                    schedule_error = None
                    try:
                        remaining = (
                            provider.remaining(pid, history, reference)
                            if not history.empty
                            else None
                        )
                    except (DataUnavailable, ValueError, KeyError, IndexError) as exc:
                        remaining = None
                        schedule_error = str(exc)
                    try:
                        prior = provider.prior(pid, weights, reference)
                    except DataUnavailable:
                        prior = None
                    calculated = per_player_week_decision(
                        name,
                        history,
                        weights,
                        cfg,
                        pid,
                        reference=reference,
                        remaining_games=remaining,
                        career_prior=prior,
                    )
                    if (
                        schedule_error
                        and calculated["status"] == "SCHEDULE_UNAVAILABLE"
                    ):
                        calculated["note"] = schedule_error
                    decision_cache[key] = calculated
                row = dict(decision_cache[key])
                row["player"] = name
            row["starter"] = name in team["starters"]
            row["positions"] = positions.get(canonical_name(name), [])
            if team.get("unsupported_scoring") and row.get("last_game_fp") is not None:
                row.update(
                    status="SCORING_INCOMPLETE",
                    decision=None,
                    p_lock=None,
                    p_wait=None,
                    note="League foul penalties unavailable; FP shown are partial estimates.",
                )
            if row["status"] in [
                "SCHEDULE_UNAVAILABLE",
                "DATA_UNAVAILABLE",
                "UNRESOLVED",
            ]:
                alerts.append(
                    {
                        "severity": "error",
                        "team": team["name"],
                        "message": name + ": " + row.get("note", "Data unavailable"),
                    }
                )
            rows.append(row)
        try:
            candidates = find_pickups(observed, team, cfg, reference, positions)
        except (DataUnavailable, ValueError, KeyError) as exc:
            candidates = []
            alerts.append(
                {
                    "severity": "error",
                    "team": team["name"],
                    "message": "Pickup analysis unavailable: " + str(exc),
                }
            )
        results.append(
            {
                "id": team["id"],
                "team_name": team["name"],
                "league_name": team.get("league_name", "Local roster"),
                "source": team.get("source", "local"),
                "season": team.get("season"),
                "league_status": team.get("league_status"),
                "synced_at": team.get("synced_at"),
                "ownership_complete": team.get("ownership_complete", False),
                "unsupported_scoring": team.get("unsupported_scoring", {}),
                "results": rows,
                "pickups": candidates,
            }
        )
    return {
        "mode": mode,
        "date": str(reference),
        "observation_cutoff": str(cutoff.date()),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "teams": results,
        "alerts": alerts,
        "dataset": provider.manifest,
        "sleeper": cfg.get("sleeper", {}),
        "notice": (
            "Historical replay: completed-game schedule, prior-season average, and current/sample rosters. Ownership is not historical."
            if mode == "replay"
            else "Live analysis. Sleeper roster freshness and scoring coverage are shown per league."
        ),
    }


def roster_dashboard(cfg, include_archived=False):
    """Show saved rosters even when the season or the live provider is unavailable."""
    teams = []
    from fetch_data import resolve_player_ids

    for t in cfg["teams"]:
        if t.get("archived") and not include_archived:
            continue
        status, note = {
            "complete": ("LEAGUE_COMPLETE", "This league has completed its season."),
            "pre_draft": (
                "PRE_DRAFT",
                "Waiting for this league's draft. Sync after drafting.",
            ),
            "drafting": ("DRAFTING", "Draft in progress. Sync to update your roster."),
        }.get(
            t.get("league_status"),
            ("DATA_UNAVAILABLE", "Refresh live data for current analysis."),
        )
        rows = []
        for name in t["players"]:
            try:
                pid = resolve_player_ids([name])[name]
            except (ValueError, KeyError):
                pid = None
            rows.append(
                {
                    "player": name,
                    "player_id": str(pid) if pid else None,
                    "status": status,
                    "decision": None,
                    "note": note,
                    "positions": t.get("player_meta", {})
                    .get(canonical_name(name), {})
                    .get("positions", []),
                    "starter": name in t["starters"],
                }
            )
        teams.append(
            {
                "id": t["id"],
                "team_name": t["name"],
                "league_name": t.get("league_name", "Local roster"),
                "source": t.get("source", "local"),
                "season": t.get("season"),
                "league_status": t.get("league_status"),
                "archived": t.get("archived", False),
                "synced_at": t.get("synced_at"),
                "ownership_complete": t.get("ownership_complete", False),
                "unsupported_scoring": t.get("unsupported_scoring", {}),
                "results": rows,
                "pickups": [],
            }
        )
    return {
        "mode": "live",
        "date": str(today()),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "teams": teams,
        "alerts": [],
        "dataset": {},
        "sleeper": cfg.get("sleeper", {}),
        "notice": "Saved Sleeper rosters. Completed and undrafted leagues have no live recommendations. Use Test Week to practice offline.",
    }
