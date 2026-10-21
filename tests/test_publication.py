import copy
import datetime as dt
from pathlib import Path
import plistlib
import subprocess

import pytest

import publication
from storage import read_json, write_json

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 10, 20, 19, tzinfo=UTC)


def report():
    return {
        "mode": "live",
        "date": "2026-10-20",
        "generated_at": NOW.isoformat(),
        "publication_id": "first",
        "refresh_status": "ok",
        "teams": [],
        "alerts": [],
        "private": "MUST_NOT_UPLOAD",
    }


@pytest.fixture
def publisher(tmp_path, monkeypatch):
    monkeypatch.setattr(publication, "LEDGER", tmp_path / "state/publication.json")
    monkeypatch.setattr("game_store.ROOT", tmp_path)
    monkeypatch.setattr(publication, "load_cfg", lambda: {})
    monkeypatch.setattr(
        publication,
        "repository",
        lambda _: ("remote", "example/repo", "https://example.github.io/repo/"),
    )
    monkeypatch.setattr(publication, "refresh_report", report)
    monkeypatch.setattr(publication, "publish_report", lambda *_: "commit")
    monkeypatch.setattr(publication, "await_visible", lambda *_: True)
    return tmp_path


def test_slot_handles_sleep_overnight_and_multiple_missed_days():
    cfg = publication.settings({})
    assert (
        publication.due_slot(dt.datetime(2026, 10, 20, 18, 16, tzinfo=UTC), cfg)
        == "2026-10-19"
    )
    assert (
        publication.due_slot(dt.datetime(2026, 10, 20, 18, 17, tzinfo=UTC), cfg)
        == "2026-10-20"
    )
    assert (
        publication.due_slot(dt.datetime(2026, 10, 23, 16, tzinfo=UTC), cfg)
        == "2026-10-22"
    )


def test_success_is_verified_then_skipped_without_network(publisher, monkeypatch):
    assert "published and verified" in publication.run(now=NOW)
    state = read_json(publication.LEDGER)
    assert state["successful_slot"] == "2026-10-20" and state["pending"] is None
    monkeypatch.setattr(
        publication,
        "repository",
        lambda _: pytest.fail("No network or Git work when done"),
    )
    assert "already completed" in publication.run(now=NOW + dt.timedelta(hours=1))


def test_push_failure_retries_after_cooldown(publisher, monkeypatch):
    def fail(*_):
        raise RuntimeError("Offline")

    monkeypatch.setattr(publication, "publish_report", fail)
    with pytest.raises(RuntimeError, match="Offline"):
        publication.run(now=NOW)
    state = read_json(publication.LEDGER)
    assert "successful_slot" not in state
    assert dt.datetime.fromisoformat(state["retry_after"]) == NOW + dt.timedelta(
        minutes=15
    )
    assert "retry window" in publication.run(now=NOW + dt.timedelta(minutes=5))
    monkeypatch.setattr(publication, "publish_report", lambda *_: "commit2")
    assert "verified" in publication.run(now=NOW + dt.timedelta(minutes=16))


def test_uploaded_report_confirmed_later_without_refetch(publisher, monkeypatch):
    monkeypatch.setattr(publication, "await_visible", lambda *_: False)
    with pytest.raises(RuntimeError, match="not confirmed"):
        publication.run(now=NOW)
    assert read_json(publication.LEDGER)["pending"]["commit"] == "commit"
    monkeypatch.setattr(publication, "visible", lambda *_: True)
    monkeypatch.setattr(
        publication,
        "refresh_report",
        lambda: pytest.fail("Don't repeat successful upload"),
    )
    assert "now live" in publication.run(now=NOW + dt.timedelta(minutes=16))


def test_partial_report_publishes_failure_but_does_not_mark_day_done(
    publisher, monkeypatch
):
    monkeypatch.setattr(
        publication, "refresh_report", lambda: {**report(), "refresh_status": "partial"}
    )
    with pytest.raises(RuntimeError, match="data alerts"):
        publication.run(now=NOW)
    state = read_json(publication.LEDGER)
    assert state["published_commit"] == "commit"
    assert "successful_slot" not in state and state["retry_after"]


def test_launch_agent_uses_calendar_catchup_and_absolute_venv_paths(tmp_path):
    root = tmp_path / "Folder With Spaces"
    config = publication.launch_agent(root, root / ".venv/bin/python", tmp_path)
    assert plistlib.loads(plistlib.dumps(config)) == config
    assert config["RunAtLoad"]
    assert config["StartCalendarInterval"] == [{"Minute": m} for m in (2, 17, 32, 47)]
    assert config["ProgramArguments"] == [
        str(root / ".venv/bin/python"),
        str(root / "publication.py"),
        "run",
    ]
    assert "--force" not in config["ProgramArguments"]


@pytest.mark.parametrize(
    "cfg",
    [
        {"branch": "main"},
        {"branch": "../main"},
        {"hour": 25},
        {"minute": -1},
        {"remote": "--upload-pack=bad"},
    ],
)
def test_invalid_publication_settings_rejected(cfg):
    with pytest.raises(ValueError):
        publication.settings({"publication": cfg})


def test_publication_branch_contains_only_exports_and_preserves_history(
    tmp_path, monkeypatch
):
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", str(remote)], check=True, capture_output=True
    )
    monkeypatch.setattr(
        publication,
        "repository",
        lambda _: (str(remote), "example/repo", "https://example.github.io/repo/"),
    )
    cfg = publication.settings({})
    first = publication.publish_report(report(), cfg)
    second = publication.publish_report({**report(), "publication_id": "second"}, cfg)
    assert first != second
    files = subprocess.check_output(
        ["git", "--git-dir", str(remote), "ls-tree", "-r", "--name-only", "gh-pages"],
        text=True,
    ).splitlines()
    assert "report.json" in files
    assert set(files) <= {
        "index.html",
        "app.js",
        "pages.js",
        "style.css",
        "icon.svg",
        "report.json",
        ".nojekyll",
    }
    content = subprocess.check_output(
        ["git", "--git-dir", str(remote), "show", "gh-pages:report.json"], text=True
    )
    assert "MUST_NOT_UPLOAD" not in content and '"publication_id": "second"' in content
    assert (
        subprocess.check_output(
            ["git", "--git-dir", str(remote), "rev-list", "--count", "gh-pages"],
            text=True,
        ).strip()
        == "2"
    )


def test_setup_requests_first_build_after_switching_source(monkeypatch):
    from types import SimpleNamespace

    calls = []

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def put(self, url, **kwargs):
            calls.append(("put", url, kwargs["json"]))
            return SimpleNamespace(status_code=204)

        def post(self, url, **kwargs):
            calls.append(("post", url))
            return SimpleNamespace(status_code=201)

    monkeypatch.setattr(publication, "github_session", Session)
    monkeypatch.setattr(
        publication,
        "repository",
        lambda _: ("remote", "example/repo", "https://example.github.io/repo/"),
    )
    assert (
        publication.configure_pages(publication.settings({}))
        == "https://example.github.io/repo/"
    )
    assert calls == [
        (
            "put",
            "https://api.github.com/repos/example/repo/pages",
            {"build_type": "legacy", "source": {"branch": "gh-pages", "path": "/"}},
        ),
        ("post", "https://api.github.com/repos/example/repo/pages/builds"),
    ]
