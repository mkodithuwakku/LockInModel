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
