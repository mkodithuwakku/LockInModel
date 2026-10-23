# Implementation Runbook: Epic 1 — Opponent-Aware Feature Pipeline & Prediction Model

**Branch:** `architecture-v2`  
**Status:** Ready for implementation  
**Prerequisites:** Epic 3 (`game_store.py` v2) and Epic 2 (`evaluator.py`) completed.  
**Reference Document:** `docs/epics/OPPONENT_AWARE_PROJECTIONS.md`

---

## 1. Outcome & Architectural Objectives

Build an advanced, opponent-aware statistical prediction pipeline in `features.py` and a regularized component prediction model in `model_ml.py`.

### Core Requirements
1. **Multi-Season Historical Training Data:**
   - Ingest existing multi-season Parquet fixtures (52,000+ player-games across 2024–25 and 2025–26) into `fact_game_logs` in `data/experiment.sqlite3` with zero network calls.
2. **Advanced Metrics Derivation (Zero External API Dependency):**
   - Derive game possessions, team pace, opponent defensive rating (DefRtg), and opponent concessions per 100 possessions directly from `fact_game_logs`.
   - Calculate opponent positional defense concessions over rolling 15-game windows.
   - Calculate schedule context: rest days, back-to-backs, and home/away factor.
3. **Component-Level Prediction Architecture:**
   - Predict individual statistical components ($\hat{\text{PTS}}, \hat{\text{REB}}, \hat{\text{AST}}, \hat{\text{STL}}, \hat{\text{BLK}}, \hat{\text{TOV}}, \hat{\text{FG3M}}$).
   - Pass predictions into `scoring.add_fantasy_points()` so the model automatically supports any custom league scoring formula and milestone bonuses.
4. **The Evaluation Gate:**
   - Add challenger policy `CHALLENGER_C1` to `evaluator.py`.
   - Objectively verify that `C1` reduces Game Forecast MAE/RMSE and reduces Weekly Lock Regret compared to Baseline `B0`.

---

## 2. File Boundaries (What to Touch vs What NOT to Touch)

### Files to Create / Modify
1. `scripts/ingest_fixtures_to_db.py` (New):
   - Ingests `data/fixtures/2025-26/games.parquet` and `data/fixtures/2025-26/priors.parquet` into `fact_game_logs` for offline training.
2. `features.py` (New):
   - Computes advanced team metrics (Pace, DefRtg), opponent concessions per 100 possessions, rest days, and positional concessions.
3. `model_ml.py` (New):
   - Trains component models (Ridge regression with closed-form $(X^TX + \lambda I)^{-1} X^Ty$ using NumPy/SciPy, requiring zero new external packages).
   - Generates opponent-adjusted stat forecasts and league-rescored projected FP.
4. `evaluator.py` (Update):
   - Add `CHALLENGER_C1` to `POLICIES` to compare against `B0`.
5. `tests/test_features.py` & `tests/test_model_ml.py` (New):
   - Unit tests for feature formulas and model training.

### Files NOT to Modify
- Do NOT modify production `lineup.py` or `publication.py` until `C1` proves superior in evaluation.
- Do NOT touch `data/lockin.sqlite3` (use `data/experiment.sqlite3`).

---

## 3. Mathematical Feature Formulations (`features.py`)

All advanced stats are computed from box scores available before the target game date.

### 3.1 Possessions & Pace
For each team game $k$:
$$\text{Possessions} = 0.5 \times \left((\text{FGA} + 0.44 \times \text{FTA} - \text{OREB} + \text{TOV})_{\text{Team}} + (\text{FGA} + 0.44 \times \text{FTA} - \text{OREB} + \text{TOV})_{\text{Opp}}\right)$$
$$\text{Pace} = 48 \times \frac{\text{Possessions}}{2 \times (\text{MIN} / 5)}$$

### 3.2 Opponent Defensive Rating & Concessions per 100 Possessions
For an opponent team $O$ over a rolling window (e.g. 15 games prior to target date):
$$\text{DefRtg}_O = 100 \times \frac{\sum \text{Points Allowed}}{\sum \text{Possessions}}$$
$$\text{Stat Conceded Rate}_{O, s} = 100 \times \frac{\sum \text{Stat } s \text{ Conceded}}{\sum \text{Possessions}} \quad \text{for } s \in \{\text{PTS, REB, AST, STL, BLK, TOV, FG3M}\}$$

$$\text{Pace Multiplier} = \frac{\text{Expected Pace}}{\text{League Mean Pace}} = \frac{(\text{Pace}_{\text{Team}} + \text{Pace}_{\text{Opp}}) / 2}{\overline{\text{Pace}}_{\text{League}}}$$

### 3.3 Opponent Positional Concessions
Rolling concessions by opponent $O$ specifically against players matching primary position $pos \in \{\text{PG, SG, SF, PF, C}\}$:
$$\text{PosConcession}_{O, pos, s} = \frac{\overline{\text{Stat } s \text{ allowed to } pos \text{ by } O}}{\overline{\text{League mean stat } s \text{ allowed to } pos}}$$

### 3.4 Rest & Schedule Context
- `rest_days`: Days since player's last game ($0 = \text{back-to-back}, 1 = \text{one day rest}, \ge 2 = \text{two+ days rest}$).
- `is_home`: $1$ if home, $0$ if away.

---

## 4. Model Architecture (`model_ml.py`)

### 4.1 Feature Vector for Player $p$ in Target Game $g$
For each stat component $s$:
$$X_{p, g} = \begin{bmatrix}
\text{Recent mean } \mu_{p, s} \text{ (10-game exponential decay)} \\
\text{Season mean } \overline{s}_p \\
\text{Recent minutes } \mu_{p, \text{MIN}} \\
\text{Pace Multiplier} \\
\text{Opponent DefRtg relative to league average} \\
\text{Opponent Positional Concession Ratio}_{O, pos, s} \\
\text{is\_home} \\
\text{is\_back\_to\_back}
\end{bmatrix}$$

### 4.2 Closed-Form Regularized Ridge Regression
To avoid bulky ML framework dependencies and ensure deterministic execution:
$$\beta_s = (X^T X + \lambda I)^{-1} X^T y_s$$
where $\lambda > 0$ is the regularization parameter (default $\lambda = 10.0$).
Predictions are clamped to nonnegative values: $\hat{s} = \max(0, X \beta_s)$.

### 4.3 League Rescoring
$$\widehat{\text{FP}} = \sum_s (\hat{s} \times \text{weight}_s) + \text{MilestoneBonuses}(\hat{s})$$

---

## 5. Verification & Acceptance Criteria

1. **Feature Pipeline Integrity:**
   - Unit tests confirm possession calculation matches Dean Oliver benchmark.
   - Rolling stats use strictly historical games (zero future data leakage).
2. **Model Training:**
   - Multi-season backfill script runs in $<5$ seconds on the Parquet fixtures.
   - Closed-form Ridge solver fits in $<1$ second across 50,000 player-games.
3. **Evaluator Benchmark:**
   - Run `evaluator.py --mode game` and confirm `CHALLENGER_C1` MAE is lower than `B0`.
   - Run `evaluator.py --mode weekly` and confirm `CHALLENGER_C1` regret $\le B0$ regret.
4. **All Tests Pass Offline:**
   ```bash
   .venv/bin/python -m pytest -q
   .venv/bin/python -m black --check *.py tests
   node --test tests/*.test.cjs
   ```
