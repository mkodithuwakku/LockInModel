import json

import pytest

import lineup
import storage
from lineup import lock_match, recommend_lineup
from storage import (
    apply_lock,
    load_locks,
    lock_history_for_league,
    locks_for_league,
    save_locks,
)

DATE = "2026-10-21"


def row(name="A", positions=None, **kwargs):
    base = dict(
        player=name,
        player_id=name,
        positions=positions or ["PG"],
        roster_slot="BN",
        schedule_state="verified",
        week_games=[
            {"date": DATE, "status": "pre_game", "opponent": "BOS", "home": True}
        ],
    )
    base.update(kwargs)
    return base


def lock_record(player_id="A", slot="PG", index=0, fp=62.5, **extra):
    record = {
        "player_id": player_id,
        "player_name": None,
        "roster_slot": slot,
        "slot_index": index,
        "locked_fp": fp,
        "game_date": "2026-10-20",
        "locked_at": "2026-10-21T04:00:00+00:00",
    }
    record.update(extra)
    return record


def test_pinned_player_keeps_its_locked_slot_against_optimizer_move():
    # Unpinned, the optimizer moves flexible A to SG for a 185-point total.
    rows = [
        row("A", ["PG", "SG"], roster_slot="PG", lineup_order=0),
        row("B", ["PG"]),
    ]
    profiles = {"A": {"projected_fp": 90}, "B": {"projected_fp": 95}}
    team = {"roster_positions": ["PG", "SG", "BN"]}
    free = recommend_lineup(team, rows, profiles, DATE)
    assert [s["player"] for s in free["slots"]] == ["B", "A"]

    locks = {"A": lock_record("A")}
    pinned = recommend_lineup(team, rows, profiles, DATE, locks=locks)
    pg, sg = pinned["slots"]
    assert pg["player"] == "A" and pg["is_pinned"] and pg["is_locked"]
    assert pg["projected_fp"] == 62.5 and pg["locked_fp"] == 62.5
    assert pg["lock_game_date"] == "2026-10-20"
    assert pg["lineup_reason"] == "Pinned starter (locked in Sleeper)"
    assert sg["player"] is None  # B cannot fill SG, so it stays open.
    assert pinned["pinned_slots"] == 1 and pinned["filled_slots"] == 1
    assert pinned["total_projected_fp"] == 62.5
    reasons = {p["player"]: p["reason"] for p in pinned["bench"]}
    assert reasons["B"] == "Lower projected total or position fit"


def test_locked_player_without_game_today_still_blocks_the_slot():
    rows = [
        row("A", ["PG"], roster_slot="PG", lineup_order=0, week_games=[]),
        row("B", ["SF"]),
    ]
    profiles = {"A": {"projected_fp": 90}, "B": {"projected_fp": 50}}
    team = {"roster_positions": ["PG", "UTIL", "BN"]}
    result = recommend_lineup(
        team, rows, profiles, DATE, locks={"A": lock_record("A", fp=33)}
    )
    assert result["slots"][0]["player"] == "A" and result["slots"][0]["is_locked"]
    assert result["slots"][0]["projected_fp"] == 33
    assert result["slots"][1]["player"] == "B"
    assert result["total_projected_fp"] == 83 and result["status"] == "ready"


def test_negative_or_missing_locked_scores_stay_pinned():
    for locked_fp in (0, -4.5, None):
        rows = [
            row("A", ["PG"], roster_slot="PG", lineup_order=0),
            row("B", ["SG"]),
        ]
        profiles = {"A": {"projected_fp": 80}, "B": {"projected_fp": 40}}
        result = recommend_lineup(
            {"roster_positions": ["PG", "SG", "BN"]},
            rows,
            profiles,
            DATE,
            locks={"A": lock_record("A", fp=locked_fp)},
        )
        pg = result["slots"][0]
        assert pg["is_locked"] and pg["player"] == "A"
        assert pg["projected_fp"] == (locked_fp if locked_fp is not None else 80)


def test_all_slots_pinned_skips_the_assignment_solver(monkeypatch):
    def fail(*args):
        raise AssertionError("optimal_assignment should not run")

    monkeypatch.setattr(lineup, "optimal_assignment", fail)
    rows = [
        row("A", ["PG"], roster_slot="PG", lineup_order=0),
        row("B", ["SG"], roster_slot="SG", lineup_order=1),
    ]
    locks = {
        "A": lock_record("A", "PG", 0, 50),
        "B": lock_record("B", "SG", 1, 40),
    }
    result = recommend_lineup(
        {"roster_positions": ["PG", "SG", "BN"]}, rows, {}, DATE, locks=locks
    )
    assert result["status"] == "ready" and result["pinned_slots"] == 2
    assert result["eligible_players"] == 0 and result["total_projected_fp"] == 90


def test_stale_conflicting_and_reserve_locks_warn_instead_of_crashing():
    rows = [
        row("A", ["PG"], roster_slot="PG", lineup_order=0),
        row("B", ["SG"], roster_slot="PG", lineup_order=0),
        row("Gone", ["C"]),
        row("Hurt", ["PF"], roster_slot="IR"),
    ]
    locks = {
        "A": lock_record("A", "PG", 0, 50),
        "B": lock_record("B", "PG", 0, 40),  # Claims A's already-pinned slot.
        "Missing": lock_record("Missing", "C", 2, 10),
        "Hurt": lock_record("Hurt", "PF", 2, 10),
    }
    profiles = {r["player_id"]: {"projected_fp": 40} for r in rows}
    result = recommend_lineup(
        {"roster_positions": ["PG", "SG", "BN"]}, rows, profiles, DATE, locks=locks
    )
    warnings = " ".join(result["pin_warnings"])
    assert "no longer on this roster" in warnings
    assert "reserve slot" in warnings
    assert "No PG slot remains for locked player B." in warnings
    assert result["slots"][0]["player"] == "A" and result["slots"][0]["is_locked"]
    # B lost its lock conflict but can still be assigned to SG as a candidate.
    assert result["slots"][1]["player"] == "B"
    assert not result["slots"][1].get("is_locked")


def test_lock_match_prefers_sleeper_id_and_falls_back_to_canonical_name():
    row_ = row("Pascal Siakam Jr.", player_id="nba:1", sleeper_id="8155")
    assert lock_match(row_, {"player_id": "8155"})
    assert lock_match(row_, {"player_id": None, "player_name": "Pascal Siakam"})
    assert lock_match(row_, {"player_name": "Pascal Siakam, Jr."})
    assert not lock_match(row_, {"player_id": "9999", "player_name": "Other"})
    assert not lock_match(row_, {})


def payload(action="lock", **overrides):
    body = {
        "league_id": "1180000000000000000",
        "schedule_week": 3,
        "action": action,
        "player": {
            "player_id": "8155",
            "player_name": "Pascal Siakam",
            "roster_slot": "PF",
            "slot_index": 4,
            "locked_fp": 41.5,
            "game_date": "2026-10-20",
        },
    }
    body.update(overrides)
    return body


def test_apply_lock_lock_unlock_and_week_rollover():
    doc = apply_lock({}, payload())
    record = doc["leagues"]["1180000000000000000"]["locks"]["8155"]
    assert record["locked_fp"] == 41.5 and record["roster_slot"] == "PF"
    assert doc["version"] == 1 and doc["updated_at"]
    assert locks_for_league(doc, "1180000000000000000", 3) == {"8155": record}
    # A different week ignores the stored locks entirely.
    assert locks_for_league(doc, "1180000000000000000", 4) == {}
    # A new-week write resets that league's container and archives the old one.
    doc = apply_lock(doc, payload(schedule_week=4))
    assert locks_for_league(doc, "1180000000000000000", 3) == {}
    assert locks_for_league(doc, "1180000000000000000", 4)
    history = lock_history_for_league(doc, "1180000000000000000")
    assert history["3"]["schedule_week"] == 3
    assert history["3"]["locks"]["8155"]["locked_fp"] == 41.5
    doc = apply_lock(doc, payload(action="unlock"))
    assert locks_for_league(doc, "1180000000000000000", 4) == {}
    # Removing a lock does not erase the previous week's archive.
    assert lock_history_for_league(doc, "1180000000000000000")["3"]["locks"]


def test_apply_lock_validates_and_archives_older_league_weeks():
    doc = {"leagues": {"1": {"schedule_week": 2, "locks": {"x": {}}}}}
    doc = apply_lock(doc, payload(league_id="2", schedule_week=3))
    # Week 2 is older than week 3: the locks stop applying but stay auditable.
    stale = doc["leagues"]["1"]
    assert stale["locks"] == {}
    assert stale["history"]["2"]["locks"] == {"x": {}}
    assert locks_for_league(doc, "1", 2) == {}
    for bad in (
        payload(league_id=""),
        payload(action="hold"),
        payload(schedule_week=None),
        payload(player=None),
        payload(player={"player_id": None, "player_name": "  "}),
    ):
        with pytest.raises(ValueError):
            apply_lock({}, bad)


def test_load_locks_recovers_from_missing_corrupt_and_wrong_shape(
    tmp_path, monkeypatch
):
    path = tmp_path / "locks.json"
    monkeypatch.setattr(storage, "LOCKS", path)
    assert load_locks() == {}
    path.write_text("{not json")
    assert load_locks() == {}
    path.write_text('["not", "a", "dict"]')
    assert load_locks() == {}
    save_locks({"version": 1, "leagues": {}})
    assert load_locks() == {"version": 1, "leagues": {}}
    # Atomic save produces parseable, indented JSON.
    assert json.loads(path.read_text())["version"] == 1
