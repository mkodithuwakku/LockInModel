"""Atomic local persistence. Personal configuration never belongs in Git."""

import copy
import json
import os
from pathlib import Path
import tempfile
import threading
import yaml

ROOT = Path(__file__).resolve().parent
LOCK = threading.RLock()
CONFIG = ROOT / "config.local.yaml"


def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".write-")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_json(path, value):
    atomic_write(path, json.dumps(value, indent=2, allow_nan=False, ensure_ascii=False))


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return copy.deepcopy(default)


def validate_config(cfg):
    if not isinstance(cfg, dict) or not isinstance(cfg.get("weights"), dict):
        raise ValueError("Configuration requires scoring weights.")
    import math

    for key, value in cfg["weights"].items():
        if key not in {
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
            "DD",
            "TD",
            "PTS40",
            "PTS50",
        }:
            raise ValueError("Unsupported scoring field: " + key)
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("Scoring weights must be finite numbers.")
    d = cfg.get("decision", {})
    for key in ("lookback_games", "recent_days"):
        if not isinstance(d.get(key), int) or not 1 <= d[key] <= 365:
            raise ValueError(key + " must be an integer between 1 and 365.")
    for key, default in [
        ("decay", 0.92),
        ("prior_weight_games", 12),
        ("sd_floor_min", 4),
        ("career_guard_scale", 0.6),
        ("rookie_guard_fp", 17.5),
        ("rare_z_threshold", 1.75),
        ("lock_bias_if_rare", 0.15),
        ("min_remaining_games_bias", 0.05),
    ]:
        value = d.get(key, default)
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError("Invalid decision setting: " + key)
    if not 0 < d.get("decay", 0.92) <= 1:
        raise ValueError("Decay must be greater than zero and at most one.")
    teams = cfg.get("teams", [])
    if not isinstance(teams, list):
        raise ValueError("Teams must be a list.")
    ids = set()
    for i, team in enumerate(teams):
        team.setdefault("id", "local-" + str(i + 1))
        if team["id"] in ids:
            raise ValueError("Duplicate team ID.")
        ids.add(team["id"])
        if not isinstance(team.get("name"), str) or not team["name"].strip():
            raise ValueError("Each team needs a name.")
        team.setdefault("players", list(team.get("starters", [])))
        for field in ("players", "starters"):
            if not isinstance(team.get(field), list) or any(
                not isinstance(n, str) or not n.strip() for n in team[field]
            ):
                raise ValueError("Player lists must contain names.")
            team[field] = list(dict.fromkeys(n.strip() for n in team[field]))
        if set(team["starters"]) - set(team["players"]):
            raise ValueError("Starters must belong to the roster.")
    return cfg


def load_cfg():
    with LOCK:
        path = CONFIG if CONFIG.exists() else ROOT / "config.yaml"
        cfg = yaml.safe_load(path.read_text())
        if not cfg.get("teams") and cfg.get("team_roster"):
            cfg["teams"] = [{"name": "My Team", "starters": cfg["team_roster"]}]
        return validate_config(cfg)


def save_cfg(cfg):
    with LOCK:
        validate_config(cfg)
        atomic_write(CONFIG, yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))


def organize_teams(cfg):
    """Keep practice rosters separate and retain old Sleeper seasons as archives."""
    synced = [t for t in cfg["teams"] if t.get("source") == "sleeper"]
    if not synced:
        return cfg
    practice = {t["id"]: t for t in cfg.get("test_teams", [])}
    for t in cfg["teams"]:
        if t.get("source") != "sleeper":
            practice.setdefault(t["id"], copy.deepcopy(t))
    cfg["test_teams"] = list(practice.values())
    newest = {}
    for t in synced:
        account = t.get("sleeper_username", "").casefold()
        newest[account] = max(newest.get(account, ""), str(t.get("season", "")))
    for t in synced:
        if str(t.get("season", "")) < newest[t.get("sleeper_username", "").casefold()]:
            t["archived"] = True
            t["archive_reason"] = "Earlier season"
    cfg["teams"] = synced
    return cfg
