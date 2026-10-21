"""Shared dashboard/report analysis; no delivery side effects."""

import datetime as dt
import pandas as pd
from zoneinfo import ZoneInfo
from storage import ROOT, load_cfg, read_json
from providers import FixtureProvider, LiveProvider
from fetch_data import canonical_name, parse_dates, get_week_bounds, player_directory
from decide import per_player_week_decision
from pickups import find_pickups, available_players
from scoring import apply_scoring_policy, effective_weights
from transport import DataUnavailable
from lineup import project_players, recommend_lineup, unavailable_lineup
from daily_badges import previous_night_badges, fantasy_night_badges, combine_badges


def today():
    return dt.datetime.now(ZoneInfo("America/Edmonton")).date()


def build_dashboard(
    mode="replay",
    reference=None,
    provider=None,
    cfg=None,
    phase="night",
    forecast_store=None,
):
    real_live_refresh = mode == "live" and provider is None
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
        FixtureProvider()
        if mode == "replay"
        else LiveProvider(dt.date.fromisoformat(str(reference or today())))
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
        if mode == "live" or phase == "night"
        else pd.Timestamp(reference) - pd.Timedelta(days=1)
    )
    observed = games[games.GAME_DATE <= cutoff]
    if mode == "live":
        # Same-day observations must be independently confirmed final. A replay
        # still uses its selected morning/night cutoff exactly as before.
        calendar = getattr(provider, "calendar", None)
        final_teams = {
            g[side]
            for g in (calendar.games if calendar else [])
            if g["date"] == str(reference)
            and g["status"] in ("complete", "final", "post_game")
            for side in ("home", "away")
        }
        current_final = observed.get(
            "TEAM_ABBREVIATION", pd.Series("", index=observed.index)
        ).isin(final_teams)
        observed = observed[(observed.GAME_DATE < cutoff) | current_final]
    daily_badges = (
        {}
        if getattr(provider, "stats_error", None)
        else previous_night_badges(observed, reference)
    )
    if mode == "replay":
        provider.include_today = phase == "morning"
    # Player directory identity may use all rows; every statistical input uses observations only.
    identity = {
        canonical_name(str(r.PLAYER_NAME)): str(r.PLAYER_ID)
        for _, r in games[["PLAYER_ID", "PLAYER_NAME"]].drop_duplicates().iterrows()
    }
    identity.update(
        {
            name: str(pid)
            for name, pid in player_directory().items()
            if name not in identity
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
    alerts = list(getattr(provider, "alerts", []))
    decision_cache = {}
    fallback = getattr(provider, "priors", None)
    if mode == "live" and hasattr(provider, "lineup_history"):
        fallback = provider.lineup_history()
    forecasts = {}
    if mode == "live" and any(
        t.get("source") == "sleeper"
        and any(m.get("sleeper_id") for m in t.get("player_meta", {}).values())
        for t in cfg["teams"]
    ):
        from projections import fetch_forecasts

        try:
            forecasts = fetch_forecasts(
                str(reference.year if reference.month >= 10 else reference.year - 1)
            )
        except DataUnavailable as exc:
            alerts.append(
                {
                    "severity": "warning",
                    "message": "Current-season projections unavailable: " + str(exc),
                }
            )
    if real_live_refresh and forecast_store is None:
        from forecast_store import ForecastStore

        forecast_store = ForecastStore()
    fantasy_badge_cache = {}
    projection_cache = {}
    for team in cfg["teams"]:
        team = apply_scoring_policy(dict(team))
        if mode == "live" and team.get("league_status", "in_season") != "in_season":
            results.extend(roster_dashboard(dict(cfg, teams=[team]))["teams"])
            continue
        weights = team.get("weights") or cfg["weights"]
        rows = []
        weights, _ = effective_weights(observed, weights)
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
        badge_weights = team.get("weights") or cfg["weights"]
        badge_key = tuple(sorted(badge_weights.items()))
        if badge_key not in fantasy_badge_cache:
            fantasy_badge_cache[badge_key] = {}
            if not getattr(provider, "stats_error", None) and not team.get(
                "unsupported_scoring"
            ):
                saved_forecasts = {}
                if mode == "live" and forecast_store is not None:
                    from forecast_store import capture_pregame

                    saved_forecasts = forecast_store.read_forecasts(
                        badge_weights, reference - dt.timedelta(days=1)
                    )
                    capture_pregame(
                        forecast_store,
                        getattr(provider, "calendar", None),
                        sleeper_players,
                        identity,
                        observed,
                        fallback,
                        forecasts,
                        badge_weights,
                        cfg,
                        reference,
                    )
                fantasy_badge_cache[badge_key] = fantasy_night_badges(
                    observed, reference, badge_weights, saved_forecasts
                )
        league_badges = fantasy_badge_cache[badge_key]
        for name in team["players"]:
            pid = identity.get(canonical_name(name))
            meta = roster_metadata(team, name, sleeper_players)
            if mode == "live" and pid is None and meta.get("sleeper_id"):
                # New rookies can precede nba_api's static identity catalog.
                pid = "sleeper:" + str(meta["sleeper_id"])
            if mode == "live" and getattr(provider, "preseason", False):
                row = {
                    "player": name,
                    "player_id": pid,
                    "status": "UPCOMING",
                    "decision": None,
                    "note": "Regular season begins "
                    + str(provider.calendar.start)
                    + ". No completed regular-season game to lock yet.",
                }
            elif mode == "live" and getattr(provider, "stats_error", None):
                row = {
                    "player": name,
                    "player_id": pid,
                    "status": "DATA_UNAVAILABLE",
                    "decision": None,
                    "note": "Performance data unavailable. Schedule and roster are still shown; no lock recommendation issued.",
                }
            elif pid is None:
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
                            provider.remaining_for_team(
                                meta.get("nba_team")
                                or (
                                    str(history.iloc[-1].get("TEAM_ABBREVIATION", ""))
                                    if not history.empty
                                    else None
                                ),
                                reference,
                            )
                            if mode == "live"
                            else (
                                provider.remaining(pid, history, reference)
                                if not history.empty
                                else None
                            )
                        )
                    except (DataUnavailable, ValueError, KeyError, IndexError) as exc:
                        remaining = None
                        schedule_error = str(exc)
                    try:
                        prior = provider.prior(pid, weights, reference)
                    except (DataUnavailable, ValueError):
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
                        previous_games=(
                            fallback[fallback.PLAYER_ID.astype(str) == pid]
                            if fallback is not None and not fallback.empty
                            else None
                        ),
                    )
                    if (
                        schedule_error
                        and calculated["status"] == "SCHEDULE_UNAVAILABLE"
                    ):
                        calculated["note"] = schedule_error
                    decision_cache[key] = calculated
                row = dict(decision_cache[key])
                row["player"] = name
            row["daily_badges"] = combine_badges(
                daily_badges.get(str(pid), []), league_badges.get(str(pid), [])
            )
            row["starter"] = name in team["starters"]
            row["positions"] = meta.get("positions") or positions.get(
                canonical_name(name), []
            )
            row["roster_slot"] = meta.get("roster_slot") or (
                "START" if row["starter"] else "BN"
            )
            row["lineup_order"] = meta.get("lineup_order", team["players"].index(name))
            row["injury_status"] = meta.get("injury_status") if mode == "live" else None
            if mode == "live":
                row["nba_team"] = meta.get("nba_team") or row.get("nba_team")
            add_week_schedule(row, provider, reference, cutoff, mode)
            if team.get("unsupported_scoring") and row.get("last_game_fp") is not None:
                row.update(
                    status="SCORING_INCOMPLETE",
                    decision=None,
                    p_lock=None,
                    p_wait=None,
                    note="Other league scoring inputs unavailable; FP shown are partial estimates.",
                )
            if row["status"] in [
                "SCHEDULE_UNAVAILABLE",
                "DATA_UNAVAILABLE",
                "UNRESOLVED",
            ] and not (
                row["status"] == "DATA_UNAVAILABLE"
                and getattr(provider, "stats_error", None)
            ):
                alerts.append(
                    {
                        "severity": "error",
                        "team": team["name"],
                        "message": name + ": " + row.get("note", "Data unavailable"),
                    }
                )
            rows.append(row)
        try:
            candidates = (
                find_pickups(observed, team, cfg, reference, positions)
                if not observed.empty and not getattr(provider, "stats_error", None)
                else []
            )
        except (DataUnavailable, ValueError, KeyError) as exc:
            candidates = []
            alerts.append(
                {
                    "severity": "error",
                    "team": team["name"],
                    "message": "Pickup analysis unavailable: " + str(exc),
                }
            )
        roster_ids = {str(r["player_id"]) for r in rows if r.get("player_id")}
        projection_key = (
            tuple(sorted((team.get("weights") or cfg["weights"]).items())),
            tuple(sorted(roster_ids)),
        )
        if projection_key not in projection_cache:
            projection_cache[projection_key] = project_players(
                observed[observed.PLAYER_ID.astype(str).isin(roster_ids)],
                (
                    fallback[fallback.PLAYER_ID.astype(str).isin(roster_ids)]
                    if fallback is not None and not fallback.empty
                    else None
                ),
                team.get("weights") or cfg["weights"],
                cfg,
                reference,
            )
        profiles = dict(projection_cache[projection_key])
        from projections import forecast_profile

        for row in rows:
            pid = str(row.get("player_id") or "")
            profile = profiles.get(pid)
            meta = roster_metadata(team, row["player"], sleeper_players)
            forecast = forecasts.get(str(meta.get("sleeper_id")))
            # Current and blended observations win; forecasts replace prior-only baselines.
            if getattr(provider, "stats_error", None):
                profile = None
            if forecast and (
                not profile
                or profile.get("projection_source")
                not in {"current_season", "blended_seasons"}
            ):
                try:
                    profile = forecast_profile(
                        forecast, team.get("weights") or cfg["weights"], reference
                    )
                except (ValueError, KeyError):
                    pass
            if (
                not row.get("history")
                and fallback is not None
                and not fallback.empty
                and pid
            ):
                from scoring import add_fantasy_points
                from fetch_data import normalize_stats_for_scoring

                old = fallback[
                    (fallback.PLAYER_ID.astype(str) == pid)
                    & (fallback.GAME_DATE < pd.Timestamp(reference))
                ]
                if not old.empty:
                    try:
                        old = (
                            add_fantasy_points(
                                normalize_stats_for_scoring(old),
                                team.get("weights") or cfg["weights"],
                            )
                            .sort_values("GAME_DATE")
                            .tail(25)
                        )
                        row["history"] = [
                            {
                                "date": str(h.GAME_DATE.date()),
                                "fp": float(h.FP),
                                **{
                                    key: float(h[stat]) if stat in old else None
                                    for key, stat in {
                                        "minutes": "MIN",
                                        "pts": "PTS",
                                        "reb": "REB",
                                        "ast": "AST",
                                        "stl": "STL",
                                        "blk": "BLK",
                                        "tov": "TOV",
                                    }.items()
                                },
                            }
                            for _, h in old.iterrows()
                        ]
                        row["history_source"] = "prior_season"
                    except (DataUnavailable, ValueError, KeyError):
                        pass
            if profile and not team.get("unsupported_scoring"):
                row["projection"] = dict(profile)
            else:
                row["projection"] = None
                row["projection_note"] = (
                    "Scoring inputs unavailable."
                    if team.get("unsupported_scoring")
                    else "No usable game history or current-season forecast."
                )
        # Approved scoring choices belong in methodology, not operational alerts.
        notes = list(
            dict.fromkeys(
                (
                    [
                        "Unavailable foul penalties omitted: "
                        + ", ".join(sorted(team["ignored_scoring"]))
                        + "."
                    ]
                    if team.get("ignored_scoring")
                    else []
                )
                + [
                    note
                    for row in rows
                    for note in (row.get("projection") or {}).get("scoring_notes", [])
                ]
            )
        )
        daily_lineup = recommend_lineup(
            team,
            rows,
            projection_cache[projection_key],
            reference,
            mode,
            blocked=(
                "Scoring inputs unavailable for this league."
                if team.get("unsupported_scoring")
                else (
                    "Fresh performance data unavailable."
                    if getattr(provider, "stats_error", None) and not forecasts
                    else None
                )
            ),
        )
        results.append(
            {
                "id": team["id"],
                "team_name": team["name"],
                "team_avatar_url": team.get("team_avatar_url"),
                "league_name": team.get("league_name", "Local roster"),
                "source": team.get("source", "local"),
                "season": team.get("season"),
                "league_status": team.get("league_status"),
                "synced_at": team.get("synced_at"),
                "ownership_complete": team.get("ownership_complete", False),
                "unsupported_scoring": team.get("unsupported_scoring", {}),
                "ignored_scoring": team.get("ignored_scoring", {}),
                "scoring_notes": notes,
                "results": rows,
                "recommended_lineup": daily_lineup,
                "pickups": candidates,
                "available_players": (
                    available_players(
                        team,
                        sleeper_players,
                        (
                            observed
                            if not getattr(provider, "stats_error", None)
                            else None
                        ),
                        cfg,
                    )
                    if mode == "live"
                    else []
                ),
            }
        )
    return {
        "mode": mode,
        "date": str(reference),
        "observation_cutoff": str(cutoff.date()),
        "schedule_week": (
            provider.calendar.display_week(reference)
            if getattr(provider, "calendar", None)
            else [str(d.date()) for d in get_week_bounds(reference)]
        ),
        "season_start": (
            str(provider.calendar.start)
            if getattr(provider, "calendar", None)
            else None
        ),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "teams": results,
        "alerts": alerts,
        "dataset": provider.manifest,
        "sleeper": cfg.get("sleeper", {}),
        "notice": (
            "Historical replay: completed-game schedule, prior-season average, and current/sample rosters. Ownership is not historical."
            if mode == "replay"
            else (
                "Regular season starts "
                + str(provider.calendar.start)
                + ". Opening-week schedule shown; no completed games to lock yet."
                if getattr(provider, "preseason", False)
                else "Live analysis. Sleeper roster freshness and scoring coverage are shown per league."
            )
        ),
    }


def roster_metadata(team, name, directory=None):
    directory = (
        directory
        if directory is not None
        else read_json(ROOT / "state/sleeper-players.json", {})
    )
    p = next(
        (
            p
            for p in directory.values()
            if canonical_name(
                p.get("full_name")
                or (p.get("first_name", "") + " " + p.get("last_name", ""))
            )
            == canonical_name(name)
        ),
        {},
    )
    saved = team.get("player_meta", {}).get(canonical_name(name), {})
    return dict(
        {
            "nba_team": p.get("team") or p.get("team_abbr"),
            "positions": p.get("fantasy_positions", []),
            "injury_status": p.get("injury_status"),
        },
        **saved
    )


def add_week_schedule(row, provider, reference, cutoff, mode):
    from fetch_data import get_week_bounds

    row["week_games"] = []
    row["schedule_state"] = "unavailable"
    try:
        if mode == "live":
            if not getattr(provider, "calendar", None):
                return
            games = provider.calendar.for_team(
                row.get("nba_team"), provider.calendar.display_week(reference)
            )
        else:
            team_code = row.get("nba_team")
            schedule = provider.schedule
            if (
                not {"TEAM_ABBREVIATION", "MATCHUP"}.issubset(schedule.columns)
                or not team_code
                or team_code not in set(schedule.TEAM_ABBREVIATION)
            ):
                return
            start, end = get_week_bounds(reference)
            games = [
                {
                    "date": str(r.GAME_DATE.date()),
                    "opponent": str(r.MATCHUP).split()[-1],
                    "home": "vs." in str(r.MATCHUP),
                    "status": "complete" if r.GAME_DATE <= cutoff else "pre_game",
                }
                for _, r in schedule[
                    (schedule.TEAM_ABBREVIATION == team_code)
                    & schedule.GAME_DATE.between(start, end)
                ].iterrows()
            ]
        history = {h["date"]: h["fp"] for h in row.get("history", [])}
        for game in games:
            # Never reveal a fixture performance beyond the observation cutoff.
            game["fp"] = (
                history.get(game["date"])
                if game["date"] <= str(cutoff.date())
                else None
            )
        row["week_games"] = games
        row["schedule_state"] = "verified"
    except DataUnavailable as exc:
        row.setdefault("warnings", []).append(str(exc))


def roster_dashboard(cfg, include_archived=False):
    """Show saved rosters even when the season or the live provider is unavailable."""
    teams = []
    directory = read_json(ROOT / "state/sleeper-players.json", {})
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
            meta = roster_metadata(t, name)
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
                    "positions": meta.get("positions", []),
                    "nba_team": meta.get("nba_team"),
                    "injury_status": meta.get("injury_status"),
                    "roster_slot": meta.get("roster_slot")
                    or ("START" if name in t["starters"] else "BN"),
                    "lineup_order": meta.get("lineup_order", t["players"].index(name)),
                    "week_games": [],
                    "schedule_state": "unavailable",
                    "starter": name in t["starters"],
                }
            )
        teams.append(
            {
                "id": t["id"],
                "team_name": t["name"],
                "team_avatar_url": t.get("team_avatar_url"),
                "league_name": t.get("league_name", "Local roster"),
                "source": t.get("source", "local"),
                "season": t.get("season"),
                "league_status": t.get("league_status"),
                "archived": t.get("archived", False),
                "synced_at": t.get("synced_at"),
                "ownership_complete": t.get("ownership_complete", False),
                "unsupported_scoring": t.get("unsupported_scoring", {}),
                "results": rows,
                "recommended_lineup": unavailable_lineup(today(), note),
                "pickups": [],
                "available_players": available_players(t, directory),
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
