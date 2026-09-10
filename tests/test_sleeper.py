import copy
import pytest
import sleeper
from transport import DataUnavailable


def payload(path):
    data = {
        "/user/example": {"user_id": "u", "display_name": "Example"},
        "/user/u/leagues/nba/2025": [{"league_id": "l"}],
        "/players/nba": {
            "1": {"full_name": "Tyrese Maxey", "fantasy_positions": ["PG"]},
            "2": {"full_name": "Derrick White", "fantasy_positions": ["SG"]},
        },
        "/league/l": {
            "name": "Test",
            "total_rosters": 2,
            "status": "complete",
            "scoring_settings": {"pts": 0.5, "tf": -2, "dd": 1},
        },
        "/league/l/rosters": [
            {"owner_id": "u", "players": ["1"], "starters": ["1"]},
            {"owner_id": "v", "players": [], "reserve": ["2"]},
        ],
        "/league/l/users": [{"user_id": "u", "metadata": {"team_name": "Test Team"}}],
    }
    return copy.deepcopy(data[path])


def test_import_records_full_ownership_and_scoring_gaps(tmp_path, monkeypatch):
    monkeypatch.setattr(sleeper, "ROOT", tmp_path)
    monkeypatch.setattr(sleeper, "get", lambda path, ttl=900: payload(path))
    monkeypatch.setattr(sleeper, "load_cfg", lambda: {"teams": []})
    saved = []
    monkeypatch.setattr(sleeper, "save_cfg", lambda c: saved.append(c))
    assert sleeper.sync("example", "2025")["count"] == 1
    t = saved[0]["teams"][0]
    assert "Derrick White" in t["owned_players"]
    assert t["unsupported_scoring"] == {"tf": -2} and t["weights"]["PTS"] == 0.5


def test_partial_import_failure_preserves_existing_teams(tmp_path, monkeypatch):
    def broken(path, ttl=900):
        if path.endswith("/rosters"):
            raise DataUnavailable("Offline")
        return payload(path)

    monkeypatch.setattr(sleeper, "ROOT", tmp_path)
    monkeypatch.setattr(sleeper, "get", broken)
    monkeypatch.setattr(
        sleeper, "save_cfg", lambda _: pytest.fail("Must not save an incomplete import")
    )
    with pytest.raises(DataUnavailable):
        sleeper.sync("example", "2025")
