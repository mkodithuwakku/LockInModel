import copy
import json

import pytest

import pages
from storage import load_cfg


def report():
    return {
        "date": "2026-10-15",
        "generated_at": "2026-10-15T18:17:00+00:00",
        "sleeper": {"username": "PRIVATE_ACCOUNT"},
        "notify": {"to_email": "PRIVATE_EMAIL"},
        "dataset": {"private_path": "PRIVATE_PATH"},
        "teams": [
            {
                "id": "test",
                "team_name": "Example",
                "league_name": "Example League",
                "owned_players": ["PRIVATE_OWNERSHIP"],
                "weights": {"PRIVATE_RULE": 1},
                "results": [
                    {
                        "player": "Example Player",
                        "player_id": "123",
                        "status": "LOCK",
                        "decision": "LOCK",
                        "p_lock": 0.9,
                        "private": "PRIVATE_PLAYER",
                        "history": [
                            {
                                "date": "2026-10-14",
                                "fp": 30,
                                "secret": "PRIVATE_HISTORY",
                            }
                        ],
                    }
                ],
                "pickups": [
                    {
                        "player": "Candidate",
                        "signal_score": 70,
                        "private": "PRIVATE_PICKUP",
                    }
                ],
            }
        ],
        "alerts": [],
    }


def test_export_allowlist_and_subpath(tmp_path):
    raw = report()
    raw["teams"].append({"archived": True, "team_name": "ARCHIVED_SECRET"})
    raw["teams"][0]["results"][0]["week_games"] = [
        {
            "date": "2026-10-14",
            "opponent": "BOS",
            "home": True,
            "fp": 30,
            "private": "PRIVATE_GAME",
        }
    ]
    out = tmp_path / "site"
    pages.export_site(raw, out)
    exported = json.loads((out / "report.json").read_text())
    assert "PRIVATE" not in json.dumps(exported)
    assert "ARCHIVED_SECRET" not in json.dumps(exported)
    assert exported["teams"][0]["results"][0]["history"][0]["fp"] == 30
    assert exported["teams"][0]["results"][0]["week_games"][0]["opponent"] == "BOS"
    html = (out / "index.html").read_text()
    assert 'data-hosting="pages"' in html
    assert "/assets/" not in html
    assert 'href="/"' not in html
    assert html.index("./pages.js") < html.index("./app.js")
    assert {p.name for p in out.iterdir()} == {
        "index.html",
        "app.js",
        "pages.js",
        "insights.js",
        "style.css",
        "icon.svg",
        "report.json",
        ".nojekyll",
        "portraits",
    }
    with pytest.raises(ValueError, match="must be empty"):
        pages.export_site(raw, out)


def test_nonfinite_data_rejected():
    raw = report()
    raw["teams"][0]["results"][0]["p_lock"] = float("nan")
    with pytest.raises(ValueError):
        pages.public_report(raw)


def test_failed_refresh_never_keeps_actions(monkeypatch, tmp_path):
    import sleeper

    cfg = copy.deepcopy(load_cfg())
    cfg["teams"] = []
    cfg["sleeper"] = {"username": "test"}
    monkeypatch.setattr(pages, "load_cfg", lambda: cfg)
    monkeypatch.setattr(pages, "SAVED", tmp_path / "report.json")
    monkeypatch.setattr(pages, "ROOT", tmp_path)
    pages.write_json(pages.SAVED, report())

    def fail():
        raise RuntimeError("PRIVATE_EXCEPTION")

    monkeypatch.setattr(sleeper, "sync_current", fail)
    monkeypatch.setattr(
        pages,
        "build_dashboard",
        lambda *a: pytest.fail("Must not query NBA after failed sync"),
    )
    result = pages.refresh_report()
    assert result["refresh_status"] == "failed"
    assert result["generated_at"] == report()["generated_at"]
    row = result["teams"][0]["results"][0]
    assert row["status"] == "DATA_UNAVAILABLE"
    assert row["decision"] is None and row["p_lock"] is None
    assert result["teams"][0]["pickups"] == []
    assert "PRIVATE" not in json.dumps(result)


def test_successful_local_refresh_uses_shared_engine(monkeypatch, tmp_path):
    import sleeper

    monkeypatch.setattr(pages, "load_cfg", lambda: {"sleeper": {"username": "test"}})
    calls = []
    monkeypatch.setattr(sleeper, "sync_current", lambda: calls.append("sync"))

    def build(mode):
        calls.append(mode)
        return report()

    monkeypatch.setattr(pages, "build_dashboard", build)
    monkeypatch.setattr(pages, "SAVED", tmp_path / "report.json")
    monkeypatch.setattr(pages, "ROOT", tmp_path)
    result = pages.refresh_report()
    assert calls == ["sync", "live"]
    assert result["refresh_status"] == "ok"
    assert result["teams"][0]["results"][0]["decision"] == "LOCK"
    assert "PRIVATE" not in pages.SAVED.read_text()
