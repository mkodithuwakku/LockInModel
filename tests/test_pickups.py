import pandas as pd
from pickups import analyze_player, find_pickups
from storage import load_cfg


def history():
    return pd.DataFrame(
        {
            "GAME_DATE": pd.date_range("2025-11-30", periods=20),
            "FP": [20] * 15 + [32] * 5,
            "MIN": [20] * 15 + [30] * 5,
            "FGM": [4] * 20,
            "FGA": [10] * 20,
            "FG3M": [1] * 20,
            "STL": [1] * 20,
            "BLK": [0] * 20,
        }
    )


def test_sustained_improvement_uses_separate_windows():
    result = analyze_player(history(), load_cfg())
    assert result["baseline_fp"] == 20 and result["recent_fp"] == 32
    assert result["qualifies"] and result["consistency"] == 1
    assert 20 < result["projected_fp"] < 32


def test_single_spike_does_not_qualify():
    h = history()
    h.FP = [20] * 19 + [80]
    assert not analyze_player(h, load_cfg())["qualifies"]


def test_tiny_history_not_ranked():
    assert analyze_player(history().tail(5), load_cfg()) is None
