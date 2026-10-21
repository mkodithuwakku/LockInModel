import copy
import pytest
import storage
from app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    cfg = storage.load_cfg()
    cfg["teams"] = [
        {
            "id": "test",
            "name": "Test Team",
            "players": ["Tyrese Maxey", "Derrick White"],
            "starters": ["Tyrese Maxey"],
        }
    ]
    monkeypatch.setattr(storage, "CONFIG", tmp_path / "config.local.yaml")
    storage.save_cfg(cfg)
    app.config.update(TESTING=True)
    return app.test_client()


def test_roster_ui_and_report_share_configuration(client):
    init = client.get("/api/bootstrap").get_json()
    response = client.post(
        "/api/roster",
        json={"team_id": "test", "action": "toggle", "player": "Derrick White"},
        headers={"X-CSRF-Token": init["csrf"]},
    )
    assert response.status_code == 200
    assert storage.load_cfg()["teams"][0]["starters"] == [
        "Tyrese Maxey",
        "Derrick White",
    ]


def test_cross_site_mutation_rejected(client):
    assert client.post("/api/roster", json={}).status_code == 403
    assert (
        client.get(
            "/api/bootstrap", headers={"Sec-Fetch-Site": "cross-site"}
        ).status_code
        == 403
    )


def test_invalid_name_does_not_modify_roster(client):
    token = client.get("/api/bootstrap").get_json()["csrf"]
    response = client.post(
        "/api/roster",
        json={"team_id": "test", "action": "add", "player": "Definitely Not A Player"},
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 400
    assert len(storage.load_cfg()["teams"][0]["players"]) == 2


def test_old_seasons_hidden_and_predraft_never_fetches_nba(client, monkeypatch):
    from engine import build_dashboard

    cfg = storage.load_cfg()
    old = dict(
        cfg["teams"][0],
        id="old",
        source="sleeper",
        season="2025",
        archived=True,
        league_status="complete",
    )
    current = dict(
        cfg["teams"][0],
        id="new",
        source="sleeper",
        season="2026",
        league_status="pre_draft",
    )
    cfg["teams"] = [old, current]
    storage.save_cfg(cfg)
    monkeypatch.setattr(
        "engine.LiveProvider",
        lambda *_: pytest.fail("No NBA request before the season"),
    )
    assert [t["id"] for t in build_dashboard("live", cfg=cfg)["teams"]] == ["new"]
    normal = client.get("/api/dashboard?mode=live").json
    assert [t["id"] for t in normal["teams"]] == ["new"]
    assert normal["teams"][0]["results"][0]["status"] == "PRE_DRAFT"
    archives = client.get("/api/dashboard?mode=live&archived=1").json
    assert {t["id"] for t in archives["teams"]} == {"new", "old"}


@pytest.mark.parametrize(
    "generated,expected",
    [
        ("2026-10-15T18:17:00+00:00", "LOCK"),
        ("2026-10-15T14:00:00+00:00", "STALE"),
        ("invalid", "STALE"),
        ("2027-10-15T18:17:00+00:00", "STALE"),
    ],
)
def test_local_report_preserves_snapshot_time_and_daily_expiry(
    client, monkeypatch, generated, expected
):
    import datetime as dt
    from types import SimpleNamespace
    import app as module

    class Clock(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 16, 18, tzinfo=dt.timezone.utc)

    monkeypatch.setattr(
        module, "dt", SimpleNamespace(datetime=Clock, timezone=dt.timezone)
    )
    monkeypatch.setattr(module, "today", lambda: dt.date(2026, 10, 16))
    saved = {
        "date": "2026-10-15",
        "generated_at": generated,
        "alerts": [],
        "teams": [
            {
                "id": "test",
                "results": [{"status": "LOCK", "decision": "LOCK"}],
                "pickups": [{"player": "Candidate"}],
            }
        ],
    }
    monkeypatch.setattr(module, "read_json", lambda *_: copy.deepcopy(saved))
    data = client.get("/api/dashboard?mode=live").get_json()
    assert data["generated_at"] == generated and data["date"] == saved["date"]
    assert data["teams"][0]["results"][0]["status"] == expected
    if expected == "STALE":
        assert data["teams"][0]["pickups"] == []


def test_daily_lineup_expires_independently_from_local_report(client, monkeypatch):
    import datetime as dt
    import app as module

    monkeypatch.setattr(module, "today", lambda: dt.date(2026, 10, 22))
    saved = {
        "date": "2026-10-21",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "alerts": [],
        "teams": [
            {
                "id": "test",
                "results": [],
                "pickups": [],
                "recommended_lineup": {
                    "date": "2026-10-21",
                    "status": "ready",
                    "slots": [{"player": "A"}],
                },
            }
        ],
    }
    monkeypatch.setattr(module, "read_json", lambda *_: copy.deepcopy(saved))
    data = client.get("/api/dashboard?mode=live").get_json()
    assert data["teams"][0]["recommended_lineup"]["status"] == "unavailable"
    assert data["teams"][0]["recommended_lineup"]["slots"] == []
