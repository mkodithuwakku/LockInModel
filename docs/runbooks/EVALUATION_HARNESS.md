# Implementation Runbook: Epic 2 — Evaluation Framework (Game Accuracy & Weekly Lock Regret)

**Branch:** `architecture-v2`  
**Status:** Ready for implementation  
**Prerequisites:** Epic 3 database normalization completed (`game_store.py` v2).  
**Reference Document:** `docs/epics/MODEL_EVALUATION.md`

---

## 1. Goal & Architecture of the Evaluation Framework

Build an offline, reproducible evaluation framework in `evaluator.py` that objectively measures decision quality across two distinct scorecards:
1. **Scorecard 1: Game Forecast Error (Per-Game)**
   - Measures how close pregame predictions were to actual observed box scores and league fantasy points.
2. **Scorecard 2: Weekly Lock Policy Regret (Per-Week Per-Team)**
   - Simulates sequential week-long decision-making without future data leakage.
   - Measures **Regret**: points left on the table compared to the retroactive weekly optimal score (Oracle).
   - Benchmarks today's production model (**Baseline 0 / B0**) against benchmark policies (Always-Wait, Fixed Thresholds, and Oracle).

---

## 2. File Boundaries (What to Touch vs What NOT to Touch)

### Files to Create / Modify
1. `evaluator.py` (New):
   - Pure evaluation engine and CLI runner.
   - Contains `evaluate_game_forecasts()` and `evaluate_weekly_lock_policy()`.
2. `tests/test_evaluator.py` (New):
   - Fast offline unit tests verifying metric calculations (MAE, RMSE, Regret) against synthetic scenarios with known mathematical outcomes.
3. `docs/agents/ARCHITECTURE_MAP.md`:
   - Add `evaluator.py` and evaluation contracts to the module map.

### Files NOT to Modify
- Do NOT modify `model.py`, `decide.py`, or `lineup.py`. The evaluator must test the *existing* logic as a black-box baseline without mutating it.
- Do NOT touch `publication.py` or `app.py`.

---

## 3. Detailed Technical Specifications

### 3.1 Scorecard 1: Game Forecast Evaluator (`evaluate_game_forecasts`)

Evaluates saved predictions against actual outcomes for a given set of observed games.

#### Input Data Contract:
A DataFrame or list of records containing for each player-game:
- `actual_fp` (`float`): League-scored fantasy points from observed box score.
- `predicted_fp` (`float`): Pregame projected fantasy points.
- `actual_stats` (`dict`): Box score components (`PTS`, `REB`, `AST`, etc.).
- `predicted_stats` (`dict`): Predicted components.

#### Metrics Calculated:
```python
def compute_forecast_metrics(actuals, predictions):
    # actuals and predictions: 1D numpy arrays of floats
    errors = actuals - predictions
    mae = float(np.mean(np.abs(errors)))
    rmse = float(np.sqrt(np.mean(errors ** 2)))
    bias = float(np.mean(errors)) # Positive = under-projecting, Negative = over-projecting
    # Pearson correlation r
    corr = float(np.corrcoef(actuals, predictions)[0, 1]) if len(actuals) > 1 and np.std(predictions) > 0 else 0.0
    return {
        "samples": len(actuals),
        "mae": round(mae, 2),
        "rmse": round(rmse, 2),
        "bias": round(bias, 2),
        "correlation": round(corr, 3)
    }
```

---

### 3.2 Scorecard 2: Weekly Lock Policy Regret (`evaluate_weekly_lock_policy`)

Simulates sequential decisions across a Monday–Sunday fantasy matchup week.

#### Temporal Boundary (No Future Leakage):
For each day $t$ in the matchup week:
1. Feed only observations $\le t$ to `per_player_week_decision()`.
2. If the policy returns `LOCK`, freeze that player's score for the week at day $t$'s game score.
3. If the policy returns `WAIT`, advance to day $t+1$.
4. On Sunday night, if no game was locked and at least one game was played, lock the final Sunday game.

#### Policies to Compare:
1. **`B0` (Production Model):** Current `per_player_week_decision()` from `decide.py` with default config.
2. **`RAW_NORMAL`:** Normal tail probability $\Phi(z)^n$ without rarity or preference heuristics.
3. **`ALWAYS_WAIT`:** Never locks until the player's final game of the week.
4. **`THRESHOLD_40`:** Locks the first game achieving $\ge 40$ FP; otherwise waits until the final game.
5. **`ORACLE` (Upper Bound):** Retrospectively selects $\max(\text{game}_1, \dots, \text{game}_k)$ for that player's week.

#### Regret Calculation:
$$\text{Regret}(\text{Policy}) = \text{Score}(\text{ORACLE}) - \text{Score}(\text{Policy})$$
$$\text{Efficiency}(\text{Policy}) = \frac{\text{Score}(\text{Policy})}{\text{Score}(\text{ORACLE})} \times 100\%$$

Lower Regret and higher Efficiency indicate superior decision quality.

---

## 4. Module Interface & CLI (`evaluator.py`)

### Public Python Functions:
```python
def evaluate_game_forecasts(games_df, profiles, weights) -> dict:
    """Computes MAE, RMSE, bias, and correlation for game forecasts."""

def simulate_weekly_lock(player_games, weights, cfg, policy="B0") -> dict:
    """Simulates a player's weekly decisions under a specified policy."""

def evaluate_season_weekly_policy(season, game_store, cfg, weights, policies=None) -> dict:
    """Evaluates all completed player-weeks in a season across multiple policies."""
```

### CLI Command:
```bash
# Run weekly lock regret evaluation on 2025-26 data
.venv/bin/python evaluator.py --mode weekly --season 2025-26

# Output JSON or pretty-printed summary table
```

---

## 5. Test Plan (`tests/test_evaluator.py`)

1. **Synthetic Metric Verification:**
   - Perfect predictions produce MAE = 0.0, RMSE = 0.0, Bias = 0.0, Correlation = 1.0.
   - Constant offset error produces MAE = offset, Bias = offset.
2. **Deterministic Weekly Simulation:**
   - Synthetic player with 3 games: [25 FP, 55 FP, 30 FP].
   - Oracle locks game 2 (55 FP, 0 regret).
   - Always-wait locks game 3 (30 FP, 25 regret).
   - Threshold 40 locks game 2 (55 FP, 0 regret).
3. **No-Future-Leakage Test:**
   - Confirm that changing future game scores on Saturday does NOT alter the policy's decision on Thursday.

---

## 6. Acceptance Criteria

1. `evaluator.py` is executable via CLI and imports cleanly.
2. `tests/test_evaluator.py` passes 100% offline with zero network calls.
3. Baseline B0 can be run on captured fixture data or local SQLite database to produce an authoritative benchmark report.
4. All existing tests continue to pass:
   ```bash
   .venv/bin/python -m pytest -q
   .venv/bin/python -m black --check *.py tests
   node --test tests/*.test.cjs
   ```
