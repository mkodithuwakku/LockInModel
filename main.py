"""Orchestrate nightly lock-in recommendations: config/load, fetch logs, decide, notify.

This version supports multiple fantasy teams (each with a name and a starters list)
and produces a grouped, sectioned report per team. It remains backward-compatible
with the old single-team `team_roster` config.
"""

import os
import datetime as dt
from collections import defaultdict
import yaml
from dotenv import load_dotenv

from fetch_data import resolve_player_ids, get_player_logs
from decide import per_player_week_decision
from notify import send_email  # we'll compose the body here

# --------------------------- config ------------------------------------------

def load_cfg():
    """Load configuration from config.yaml."""
    with open("config.yaml", "r") as f:
        return yaml.safe_load(f)

def already_ran_today() -> bool:
    path = "state/last_run.txt"
    if not os.path.exists(path):
        return False
    with open(path, "r") as f:
        last = f.read().strip()
    today = str(dt.date.today())
    return last == today

def stamp_today():
    os.makedirs("state", exist_ok=True)
    with open("state/last_run.txt", "w") as f:
        f.write(str(dt.date.today()))

# ---------------------- report composition -----------------------------------

def _fmt2(x):
    try:
        xf = float(x)
        return f"{xf:.2f}"
    except Exception:
        return "NA"

def compose_report_grouped(teams_results):
    """
    teams_results: list of dicts like
      {
        "team_name": "Team A",
        "results": [ per_player dicts returned by per_player_week_decision ... ]
      }
    """
    lines = []
    lines.append("Fantasy Lock-in Recommendations (tonight)")
    lines.append("")  # spacer

    for bucket in teams_results:
        team_name = bucket["team_name"]
        results = bucket["results"]

        lines.append(f"## {team_name}")
        lines.append("")

        # Keep same per-player line style you already use
        for r in results:
            if "note" in r and r["note"]:
                lines.append(f"- {r['player']}: {r['note']}")
                continue

            last_date = r.get("last_game_date", "NA")
            last_fp   = _fmt2(r.get("last_game_fp", "nan"))
            p_lock    = _fmt2(r.get("p_lock", "nan"))
            rarity    = _fmt2(r.get("rarity_score", "nan"))
            rem       = r.get("remaining_games_est", 0)
            decision  = r.get("decision", "WAIT")
            pad = " " if decision == "LOCK" else " "

            lines.append(
                f"- {r['player']}: {decision}{pad} "
                f"(last {last_date} = {last_fp} FP; p_lock={p_lock}, rarity={rarity}, rem={rem})"
            )

        lines.append("")  # spacer between teams

    return "\n".join(lines).strip() + "\n"

# ----------------------------- main ------------------------------------------

def main():
    load_dotenv()
    cfg = load_cfg()
    weights = cfg["weights"]

    # Support both legacy single-team and new multi-team configs
    # New structure (recommended):
    # teams:
    #   - name: Team One
    #     starters: ["Player A", "Player B", ...]
    #   - name: Team Two
    #     starters: ["Player X", "Player Y", ...]
    #
    # Legacy:
    # team_roster: ["Player A", "Player B", ...]
    teams_cfg = cfg.get("teams")

    if teams_cfg and isinstance(teams_cfg, list):
        teams = [
            {"name": t.get("name", f"Team {i+1}"), "starters": list(t.get("starters", []))}
            for i, t in enumerate(teams_cfg)
        ]
    else:
        # Backward-compatible single team bucket
        roster = list(cfg.get("team_roster", []))
        teams = [{"name": "My Team", "starters": roster}]

    # Build a unique set of all player names we need to resolve/fetch
    all_names = []
    for t in teams:
        all_names.extend(t["starters"])
    # Remove empties and duplicates while preserving order
    seen = set()
    dedup_names = []
    for n in all_names:
        if not n or not isinstance(n, str):
            continue
        key = n.strip()
        if key and key not in seen:
            seen.add(key)
            dedup_names.append(key)

    # Resolve player IDs once for all teams
    pid_map = resolve_player_ids(dedup_names)

    # Fetch logs once per unique player id (cache)
    logs_cache = {}
    for name, pid in pid_map.items():
        try:
            logs_cache[name] = get_player_logs(pid, season=None, last_n_days=60)
        except Exception as e:
            logs_cache[name] = None  # store a sentinel; we'll show an error per player

    # Compute decisions per team
    teams_results = []
    for t in teams:
        t_name = t["name"]
        starters = t["starters"]
        bucket = {"team_name": t_name, "results": []}

        for name in starters:
            pid = pid_map.get(name)
            if pid is None:
                bucket["results"].append({"player": name, "note": "Unresolved player name"})
                continue

            logs = logs_cache.get(name)
            try:
                res = per_player_week_decision(name, logs, weights, cfg,player_id=pid)
            except Exception as e:
                res = {"player": name, "note": f"Error: {e}"}
            bucket["results"].append(res)

        teams_results.append(bucket)

    # Build grouped report body
    body = compose_report_grouped(teams_results)

    # Notify (same as before)
    method = cfg["notify"]["method"]
    subject = f"Fantasy Lock-in Recommendations — {dt.date.today().isoformat()}"

    if method == "email":
        send_email(
            subject=subject,
            body=body,
            to_email=cfg["notify"]["to_email"],
            from_email=cfg["notify"]["from_email"],
        )
    else:
        # default to email if you haven't wired another path
        send_email(
            subject=subject,
            body=body,
            to_email=cfg["notify"]["to_email"],
            from_email=cfg["notify"]["from_email"],
        )

    # Stamp & echo
    os.makedirs("state", exist_ok=True)
    stamp_today()
    print(body)

if __name__ == "__main__":
    main()
