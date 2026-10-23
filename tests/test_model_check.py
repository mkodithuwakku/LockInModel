import datetime as dt
import json

import pytest

import model_check


@pytest.fixture
def check(monkeypatch, tmp_path):
    monkeypatch.setattr(model_check, "LEDGER", tmp_path / "model_check.json")
    monkeypatch.setattr(model_check, "HISTORY", tmp_path / "history.jsonl")
    monkeypatch.setattr(model_check, "load_cfg", lambda: {"weights": {}})
    monkeypatch.setattr(
        model_check,
        "build_report",
        lambda cfg, now: {"ran_at": now.isoformat(), "sections": {}, "errors": []},
    )
    return model_check


def test_run_gates_to_biweekly_interval_and_appends_history(check):
    day = dt.datetime(2026, 1, 5, 12, tzinfo=dt.timezone.utc)
    assert check.run(now=day).startswith("Model check complete")
    assert check.run(now=day + dt.timedelta(days=5)) == "Model check not due yet."
    assert check.run(now=day + dt.timedelta(days=13, hours=23)) == (
        "Model check not due yet."
    )
    assert check.run(now=day + dt.timedelta(days=14)).startswith("Model check complete")
    lines = check.HISTORY.read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["ran_at"] == day.isoformat()


def test_failed_run_backs_off_then_retries(check, monkeypatch):
    day = dt.datetime(2026, 1, 5, 12, tzinfo=dt.timezone.utc)
    monkeypatch.setattr(
        check,
        "build_report",
        lambda cfg, now: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with pytest.raises(RuntimeError):
        check.run(now=day)
    assert check.run(now=day + dt.timedelta(hours=2)) == (
        "Waiting for model check retry window."
    )
    monkeypatch.setattr(
        check,
        "build_report",
        lambda cfg, now: {"ran_at": now.isoformat(), "sections": {}, "errors": []},
    )
    assert check.run(now=day + dt.timedelta(hours=7)).startswith("Model check complete")


def test_launch_agent_ticks_quarter_hourly_for_wake_catchup(check, tmp_path):
    agent = check.launch_agent(tmp_path, tmp_path / "python", tmp_path)
    assert agent["Label"] == "com.lockin.modelcheck"
    assert agent["StartCalendarInterval"] == [{"Minute": m} for m in (0, 15, 30, 45)]
    assert agent["RunAtLoad"] is True
    assert agent["ProgramArguments"][1].endswith("model_check.py")


def test_summarize_reports_paired_weekly_and_tune():
    report = {
        "sections": {
            "live": {
                "game": {
                    "paired": {
                        "samples": 10,
                        "B0": {"mae": 5.2},
                        "CHALLENGER_C1": {"mae": 5.1},
                    }
                },
                "weekly": {
                    "B0": {"regret_total": 100.0},
                    "CHALLENGER_C1": {"regret_total": 90.0},
                },
            },
            "tune": {
                "results": [{"lam": 10.0, "window": 15, "decay": 0.92, "mae": 5.0}]
            },
        },
        "errors": [{"live": "x"}],
    }
    text = model_check.summarize(report)
    assert "B0 5.20 vs ridge 5.10" in text
    assert "regret B0 100.0 vs ridge 90.0" in text
    assert "best tune lam=10.0" in text
    assert "1 section error" in text
    assert model_check.summarize({"sections": {}, "errors": []}) == (
        "Model check complete."
    )
