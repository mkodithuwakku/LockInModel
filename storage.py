"""Atomic local persistence. Personal configuration never belongs in Git."""

import copy
import datetime as dt
import json
import logging
import os
from pathlib import Path
import tempfile
import threading
import yaml
from scoring import apply_scoring_policy, supported_stat

ROOT = Path(__file__).resolve().parent
LOCK = threading.RLock()
CONFIG = ROOT / "config.local.yaml"
LOCKS = ROOT / "state/locks.json"
LOCKS_VERSION = 1


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

    def validate_weights(weights):
        if not isinstance(weights, dict):
            raise ValueError("Scoring weights must be a mapping.")
        for key, value in weights.items():
            if not supported_stat(key):
                raise ValueError("Unsupported scoring field: " + key)
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("Scoring weights must be finite numbers.")

    validate_weights(cfg["weights"])
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
        apply_scoring_policy(team)
        if "weights" in team:
            validate_weights(team["weights"])
        team.setdefault("id", "local-" + str(i + 1))
        if team["id"] in ids:
            raise ValueError("Duplicate team ID.")
        ids.add(team["id"])
        if not isinstance(team.get("name"), str) or not team["name"].strip():
            raise ValueError("Each team needs a name.")
        slots = team.get("roster_positions")
        if slots is not None:
            if not isinstance(slots, list) or any(
                not isinstance(s, str) or not s.strip() for s in slots
            ):
                raise ValueError("Roster positions must be a list of slot names.")
            team["roster_positions"] = [s.strip().upper() for s in slots]
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


def load_locks():
    """Manager-reported Sleeper lock flags; corrupt files fail closed."""
    try:
        data = json.loads(LOCKS.read_text())
    except FileNotFoundError:
        return {}
    except (ValueError, OSError) as exc:
        logging.getLogger(__name__).warning("Ignoring unreadable locks file: %s", exc)
        return {}
    return data if isinstance(data, dict) else {}


def save_locks(locks):
    if not isinstance(locks, dict):
        raise ValueError("Locks document must be a mapping.")
    write_json(LOCKS, locks)


def locks_for_league(locks, league_id, week_key):
    """Locks for one league, only while the stored fantasy week is current."""
    if not league_id or week_key is None or not isinstance(locks, dict):
        return {}
    record = (locks.get("leagues") or {}).get(str(league_id))
    if not isinstance(record, dict) or record.get("schedule_week") != week_key:
        return {}
    return {
        str(key): value
        for key, value in (record.get("locks") or {}).items()
        if isinstance(value, dict)
    }


def _older_week(stored, current):
    """Week keys are only comparable within the same kind (int or date string)."""
    if isinstance(stored, int) and isinstance(current, int):
        return stored < current
    if isinstance(stored, str) and isinstance(current, str):
        return stored < current
    return False


def apply_lock(doc, payload):
    """Validate and apply one phone-reported lock/unlock to the document."""
    from fetch_data import canonical_name

    if not isinstance(payload, dict):
        raise ValueError("Expected a lock request object.")
    league = str(payload.get("league_id") or "").strip()
    week = payload.get("schedule_week")
    action = payload.get("action")
    player = payload.get("player")
    if not league.isdigit():
        raise ValueError("A Sleeper league id is required.")
    if action not in ("lock", "unlock"):
        raise ValueError("Action must be 'lock' or 'unlock'.")
    if not isinstance(week, int) and not (isinstance(week, str) and week.strip()):
        raise ValueError("A schedule week is required.")
    if isinstance(week, str):
        week = week.strip()
    if not isinstance(player, dict):
        raise ValueError("A player object is required.")
    name = str(player.get("player_name") or "").strip()
    key = str(player.get("player_id") or "").strip() or canonical_name(name)
    if not key:
        raise ValueError("A player id or name is required.")

    doc = dict(doc or {})
    leagues = dict(doc.get("leagues") or {})
    container = dict(leagues.get(league) or {})
    if container.get("schedule_week") != week:
        container = {"schedule_week": week, "locks": {}}
    records = dict(container.get("locks") or {})
    if action == "lock":
        slot_index = player.get("slot_index")
        records[key] = {
            "player_id": str(player.get("player_id") or "") or None,
            "player_name": name or None,
            "canonical_name": canonical_name(name) if name else None,
            "roster_slot": str(player.get("roster_slot") or "") or None,
            "slot_index": slot_index if isinstance(slot_index, int) else None,
            "locked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "locked_fp": (
                player["locked_fp"]
                if isinstance(player.get("locked_fp"), (int, float))
                else None
            ),
            "game_date": str(player.get("game_date") or "") or None,
        }
    else:
        records.pop(key, None)
        if name:
            records.pop(canonical_name(name), None)
    container["locks"] = records
    # Expired weeks never linger; only compare keys of the same kind.
    leagues = {
        str(lid): record
        for lid, record in leagues.items()
        if not _older_week(
            (record or {}).get("schedule_week") if isinstance(record, dict) else None,
            week,
        )
    }
    leagues[league] = container
    doc.update(
        version=LOCKS_VERSION,
        updated_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        leagues=leagues,
    )
    return doc


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
