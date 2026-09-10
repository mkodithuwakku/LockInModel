import copy
import datetime as dt
from pathlib import Path
import pytest
from storage import ROOT, load_cfg, read_json
from engine import build_dashboard
from providers import FixtureProvider
from transport import DataUnavailable
import main


def sample_cfg():
    c = load_cfg()
    c["teams"] = [
        {
            "id": "sample",
            "name": "Sample",
            "players": ["Tyrese Maxey"],
            "starters": ["Tyrese Maxey"],
        }
    ]
    return c


@pytest.mark.skipif(
    not (ROOT / "data/fixtures/2025-26/manifest.json").exists(),
    reason="Capture the historical dataset first",
)
def test_real_fixture_replays_offline_and_hides_future():
    p = FixtureProvider()
    cfg = sample_cfg()
    date = p.manifest["default_date"]
    a = build_dashboard(provider=p, cfg=cfg, reference=date)
    p.games.loc[p.games.GAME_DATE > date, "PTS"] = 999
    b = build_dashboard(provider=p, cfg=cfg, reference=date)
    assert a["teams"] == b["teams"]
    assert all(h["date"] <= date for h in a["teams"][0]["results"][0]["history"])


@pytest.mark.skipif(
    not (ROOT / "data/fixtures/2025-26/manifest.json").exists(),
    reason="Capture the historical dataset first",
)
def test_incomplete_scoring_never_recommends_lock():
    p = FixtureProvider()
    cfg = sample_cfg()
    cfg["teams"][0]["unsupported_scoring"] = {"tf": -2}
    report = build_dashboard(provider=p, cfg=cfg, reference=p.manifest["default_date"])
    row = report["teams"][0]["results"][0]
    assert row["status"] == "SCORING_INCOMPLETE" and row["decision"] is None
    assert report["alerts"]


def test_replay_cannot_send_email():
    with pytest.raises(ValueError):
        main.run(live=False, send=True)


def test_email_failure_is_not_retried(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    monkeypatch.setenv("EMAIL_USER", "example@example.com")
    monkeypatch.setenv("EMAIL_APP_PASSWORD", "test-password")
    calls = []

    def fail(*a):
        calls.append(a)
        raise TimeoutError()

    monkeypatch.setattr(main, "send_email", fail)
    cfg = {
        "notify": {
            "to_email": "example@example.com",
            "from_email": "example@example.com",
        }
    }
    with pytest.raises(RuntimeError):
        main.send_daily("subject", "body", cfg)
    assert "Already attempted" in main.send_daily("subject", "body", cfg)
    assert len(calls) == 1


def test_exposed_password_is_blocked_before_smtp(tmp_path, monkeypatch):
    import hashlib
    from storage import write_json

    monkeypatch.setattr(main, "ROOT", tmp_path)
    monkeypatch.setenv("EMAIL_USER", "example@example.com")
    monkeypatch.setenv("EMAIL_APP_PASSWORD", "old")
    write_json(
        tmp_path / "state/credential-review.json",
        {"blocked_password_sha256": hashlib.sha256(b"old").hexdigest()},
    )
    with pytest.raises(ValueError, match="publicly committed"):
        main.send_daily("a", "b", {"notify": {}})


def test_pickup_alerts_have_cooldown_and_material_change_override():
    item = {
        "player_id": "1",
        "scoring_complete": True,
        "team_gain": 5,
        "signal_score": 70,
        "projected_fp": 30,
    }
    report = {"teams": [{"id": "t", "ownership_complete": True, "pickups": [item]}]}
    first, updates = main.new_pickup_alerts(report, {}, 100)
    assert len(first["teams"][0]["pickups"]) == 1
    second, _ = main.new_pickup_alerts(report, updates, 200)
    assert second["teams"][0]["pickups"] == []
    item["signal_score"] = 82
    changed, _ = main.new_pickup_alerts(report, updates, 300)
    assert len(changed["teams"][0]["pickups"]) == 1


@pytest.mark.skipif(
    not (ROOT / "data/fixtures/2025-26/manifest.json").exists(),
    reason="Capture the historical dataset first",
)
def test_flagrants_do_not_change_model_or_pickup_scoring():
    provider = FixtureProvider()
    cfg = sample_cfg()
    reference = provider.manifest["default_date"]
    expected = build_dashboard(provider=provider, cfg=cfg, reference=reference)
    cfg["teams"][0]["unsupported_scoring"] = {"ff": -2}
    actual = build_dashboard(provider=provider, cfg=cfg, reference=reference)
    assert actual["teams"][0]["results"] == expected["teams"][0]["results"]
    assert actual["teams"][0]["pickups"] == expected["teams"][0]["pickups"]
    assert actual["alerts"] == expected["alerts"]
    assert actual["teams"][0]["ignored_scoring"] == {"ff": -2}
