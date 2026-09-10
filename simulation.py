"""Persistent, offline practice week with a clock and user-banked scores."""

import copy
import datetime as dt
import uuid
import yaml
from engine import build_dashboard
from providers import FixtureProvider
from storage import ROOT, LOCK, load_cfg, read_json, write_json, validate_config

PATH = ROOT / "state/test-week.json"


def new_run(provider, cfg):
    teams = copy.deepcopy(
        cfg.get("test_teams")
        or [t for t in cfg["teams"] if t.get("source") != "sleeper"]
    )
    if not teams:
        teams = validate_config(yaml.safe_load((ROOT / "config.yaml").read_text()))[
            "teams"
        ]
    # Test rules and rosters are deliberate practice inputs, never live Sleeper settings.
    for team in teams:
        team.update(source="local", league_name="Practice league · sample scoring")
    return {
        "version": 1,
        "revision": uuid.uuid4().hex,
        "date": provider.manifest["week_start"],
        "phase": "morning",
        "locks": {},
        "cfg": {
            "weights": copy.deepcopy(cfg["weights"]),
            "decision": copy.deepcopy(cfg["decision"]),
            "teams": teams,
        },
    }


def load_run(provider, cfg):
    run = read_json(PATH)
    if not run:
        run = new_run(provider, cfg)
        write_json(PATH, run)
    if (
        not provider.manifest["week_start"]
        <= run["date"]
        <= provider.manifest["week_end"]
    ):
        raise ValueError(
            "Saved run does not match this dataset. Restart the test week."
        )
    return run


def report(run, provider):
    data = build_dashboard(
        "replay", run["date"], provider, run["cfg"], phase=run["phase"]
    )
    for team in data["teams"]:
        banked = run["locks"].get(team["id"], {})
        for row in team["results"]:
            row["banked"] = banked.get(row["player"])
            row["can_bank"] = bool(
                row.get("decision") and row["starter"] and not row["banked"]
            )
            if row["banked"]:
                row["model_status"] = row["status"]
                row.update(status="BANKED", decision=None, p_lock=None, p_wait=None)
        team["banked_total"] = round(sum(v["fp"] for v in banked.values()), 2)
        team["banked_count"] = len(banked)
        team["night_results"] = [
            dict(player=r["player"], player_id=r.get("player_id"), **h)
            for r in team["results"]
            for h in r.get("history", [])
            if h["date"] == run["date"] and run["phase"] == "night"
        ]
    data["simulation"] = {k: run[k] for k in ["revision", "date", "phase"]}
    data["simulation"]["finished"] = (
        run["date"] == provider.manifest["week_end"] and run["phase"] == "night"
    )
    data["notice"] = (
        "Offline practice · sample rosters and scoring; league ownership is unknown. "
        "Morning hides tonight’s results. Bank one score per starter; restart to undo. No Sleeper changes or email."
    )
    return data


def get_report():
    with LOCK:
        provider = FixtureProvider()
        return report(load_run(provider, load_cfg()), provider)


def act(body):
    with LOCK:
        provider = FixtureProvider()
        cfg = load_cfg()
        run = load_run(provider, cfg)
        if body.get("revision") != run["revision"]:
            raise ValueError(
                "The test week changed in another request. Reload before continuing."
            )
        action = body.get("action")
        if action == "reset":
            run = new_run(provider, cfg)
        elif action == "advance":
            if run["phase"] == "morning":
                run["phase"] = "night"
            elif run["date"] < provider.manifest["week_end"]:
                run["date"] = str(
                    dt.date.fromisoformat(run["date"]) + dt.timedelta(days=1)
                )
                run["phase"] = "morning"
            else:
                raise ValueError(
                    "The week is complete. Bank remaining scores or restart."
                )
        elif action == "bank":
            data = report(run, provider)
            team = next(
                (t for t in data["teams"] if t["id"] == body.get("team_id")), None
            )
            row = next(
                (
                    r
                    for r in (team or {}).get("results", [])
                    if r["player"] == body.get("player")
                ),
                None,
            )
            if not row or not row["can_bank"]:
                raise ValueError(
                    "Only an unlocked starter with a verified completed score can be banked."
                )
            run["locks"].setdefault(team["id"], {})[row["player"]] = {
                "fp": row["last_game_fp"],
                "game_date": row["last_game_date"],
                "banked_on": run["date"],
                "model_status": row["status"],
            }
        elif action in ["toggle", "add", "remove"]:
            team = next(
                (t for t in run["cfg"]["teams"] if t["id"] == body.get("team_id")), None
            )
            name = body.get("player")
            if not team or not isinstance(name, str) or not name.strip():
                raise ValueError("Select a practice team and player.")
            if run["phase"] != "morning":
                raise ValueError(
                    "Edit the practice roster in the morning before revealing games."
                )
            name = name.strip()
            if name in run["locks"].get(team["id"], {}):
                raise ValueError(
                    "A banked player stays in the lineup until the week restarts."
                )
            if action == "add":
                from fetch_data import resolve_player_ids

                resolve_player_ids([name])
                if len(team["players"]) >= 40:
                    raise ValueError("Practice rosters support at most 40 players.")
                if name not in team["players"]:
                    team["players"].append(name)
            elif name not in team["players"]:
                raise ValueError("Player is not on this practice roster.")
            elif action == "remove":
                team["players"].remove(name)
                team["starters"] = [n for n in team["starters"] if n != name]
            elif name in team["starters"]:
                team["starters"].remove(name)
            else:
                team["starters"].append(name)
        else:
            raise ValueError("Unknown test week action.")
        run["revision"] = uuid.uuid4().hex
        # Compute successfully before persisting any change.
        result = report(run, provider)
        write_json(PATH, run)
        return result
