# Agent Reference: Workflows, Testing, & Verification

This document contains testing protocols, verification commands, development workflows, and guidelines to avoid common pitfalls.

---

## 1. Environment & Execution Setup

- **Working Directory:** Commands must be executed from inside `LockInModel/` (the git repository root).
- **Virtual Environment:** Python venv is at `.venv/`. Always invoke `.venv/bin/python` rather than system Python or conda Python to ensure dependencies like `nba_api`, `pandas`, `scipy`, `pytest`, `black` are available.

```bash
cd "/Users/mkodi/Personal Coding/LockInModel/LockInModel"
source .venv/bin/activate
```

---

## 2. Test Suites & Verification

### Complete Verification Pipeline
Always run all three checks before completing non-documentation changes:

```bash
# 1. Python unit and regression tests (256 tests)
.venv/bin/python -m pytest -q

# 2. Code formatting check
.venv/bin/python -m black --check *.py tests

# 3. Node.js frontend policy & client logic tests (52 tests)
node --test tests/*.test.cjs
```

### Targeted Testing (Token & Time Saving)
When modifying a specific component, run its corresponding test file first:

| Subsystem Modified | Targeted Test Command |
| :--- | :--- |
| Core modeling & decisions | `.venv/bin/python -m pytest tests/test_core.py` |
| Positional lineup optimizer | `.venv/bin/python -m pytest tests/test_lineup.py` |
| Locked-player pinning & storage | `.venv/bin/python -m pytest tests/test_lineup_pinning.py` |
| Opponent features & Ridge model | `.venv/bin/python -m pytest tests/test_features.py tests/test_model_ml.py` |
| Evaluation harness & tuning | `.venv/bin/python -m pytest tests/test_evaluator.py` |
| Biweekly model-check runner | `.venv/bin/python -m pytest tests/test_model_check.py` |
| Projections & Sleeper parsing | `.venv/bin/python -m pytest tests/test_projections.py` |
| Daily badges & leaderboards | `.venv/bin/python -m pytest tests/test_daily_badges.py tests/test_badge_awards.py` |
| Season badge store & ledger | `.venv/bin/python -m pytest tests/test_badge_store.py` |
| Season review aggregates | `.venv/bin/python -m pytest tests/test_season_review.py` |
| Pickups & schedule-aware swaps | `.venv/bin/python -m pytest tests/test_pickups.py` |
| SQLite game store | `.venv/bin/python -m pytest tests/test_game_store.py` |
| Sleeper API / stats fallback | `.venv/bin/python -m pytest tests/test_sleeper.py tests/test_sleeper_stats.py` |
| Static export & publication | `.venv/bin/python -m pytest tests/test_publication.py tests/test_pages.py` |
| Practice simulator (Test Week) | `.venv/bin/python -m pytest tests/test_simulation.py` |
| Client-side logic & pinning | `node --test tests/insights.test.cjs tests/lineup_pinning.test.cjs tests/pages.test.cjs tests/season_review.test.cjs` |

---

## 3. Key Development Rules & Invariants

1. **No External Network in Unit Tests:**
   - Tests prohibit real socket connections (`tests/conftest.py` blocks outbound networking).
   - Use mock payloads or fixture tables.
2. **Never Fabricate Data:**
   - Missing data must remain missing (`null`, `—`, or labeled `DATA_UNAVAILABLE` / `SCORING_INCOMPLETE`).
   - Do not backfill missing pregame forecasts with postgame values.
   - Do not claim predictive accuracy from descriptive statistics or historical replays.
3. **Roster-First Interface Mandate:**
   - The roster sheet is the primary view on both desktop and mobile.
   - Never displace the roster sheet above the fold with informational panels, banners, or insights.
   - Roster order: recommended starters in designated slots, followed by bench and reserves.
4. **Strict Color Palette Guidelines:**
   - Charcoal base (`#17191b` / `#1e2023`) with subtle plum undertone and muted purple accents.
   - Soft gold for small details/accents; do not use saturated yellows or large plum blocks.
   - Performance colours: green (above personal baseline), amber (near baseline $\pm 10\%$, min 2 FP), red (below baseline).
5. **Keep the README Current:**
   - Any code change impacting architecture, CLI, models, or workflows requires updating `README.md` and related docs in `docs/` in the same commit.

---

## 4. Common Developer Tasks

### Local Interactive Server
```bash
.venv/bin/python app.py
# Server binds to http://127.0.0.1:8765
```

### Static Website Publication (macOS)
```bash
# Check scheduled publication status
.venv/bin/python publication.py status

# Force immediate publication of live data and assets to gh-pages branch
.venv/bin/python publication.py run --force
```

### Historical Replay CLI
```bash
# Run end-of-day report using captured fixtures (no network required)
.venv/bin/python main.py --date 2025-12-25
```

### v2 Database Migration
```bash
# Copy legacy JSON-payload games into the normalized schema (source stays read-only)
.venv/bin/python scripts/migrate_v2_db.py --src data/lockin.sqlite3 --dest data/experiment.sqlite3

# Point the app at an isolated database instead of data/lockin.sqlite3
LOCKIN_DB_PATH="data/experiment.sqlite3" .venv/bin/python app.py
```

### Offline Evaluation CLI
```bash
# Weekly lock-policy regret vs Oracle over a season's stored games (solo player-weeks)
.venv/bin/python evaluator.py --mode weekly --season 2026-27 --db data/experiment.sqlite3

# Slot-constrained team-weekly lock regret (SOLO_B0/C1 vs ROSTER_B0/C1 vs TEAM_ORACLE)
.venv/bin/python evaluator.py --mode team-weekly --season 2025-26 --db data/experiment.sqlite3

# Walk-forward game-forecast backtest: B0 production baseline vs CHALLENGER_C1
.venv/bin/python evaluator.py --mode game --season 2025-26 --db data/experiment.sqlite3

# Hyperparameter grid search (lam x window x decay) ranked by walk-forward MAE
.venv/bin/python evaluator.py --mode tune --db data/experiment.sqlite3
```
Policies (`--mode weekly`): `B0` (production `decide.per_player_week_decision`), `RAW_NORMAL`,
`ALWAYS_WAIT`, `THRESHOLD_40`, `CHALLENGER_C1` (opponent-aware Ridge model),
`ORACLE`. Team policies (`--mode team-weekly`): `SOLO_B0`, `ROSTER_B0` (with Stage 2
`decide.apply_roster_lock_context` slot contention), `SOLO_C1`, `ROSTER_C1`,
`ALWAYS_WAIT`, `THRESHOLD_40`, `TEAM_ORACLE`. `--policies` selects a subset,
`--limit` caps player-weeks, team-weeks, or slate dates. `data/experiment.sqlite3`
holds ingested Parquet fixtures for training. The evaluator is read-only, so
`--db data/lockin.sqlite3` is safe for prospective live-season metrics — but
never train/tune against it.

### Biweekly model check

The Ridge model refits on every refresh; `model_check.py` evaluates and
recommends knob changes every ~14 days via the `com.lockin.modelcheck`
LaunchAgent (same 15-minute tick + wake catch-up as the publisher — see
`docs/HOSTING.md`). It writes `state/model_check.json` plus an append-only
`state/model_check_history.jsonl`. To run it manually — or understand what
each section does:

1. **Live-season scorecard** (prospective, real data):
   `.venv/bin/python evaluator.py --mode game --db data/lockin.sqlite3` —
   compares `CHALLENGER_C1` vs `B0` MAE/RMSE/correlation on this season's
   games and also scores saved `forecast_snapshots` rows.
   `.venv/bin/python evaluator.py --mode weekly --db data/lockin.sqlite3` —
   weekly lock regret, ridge vs baseline, on real weeks. Early season has few
   samples; small gaps are noise.
2. **Retune if the ridge lags or drift shows**:
   `.venv/bin/python evaluator.py --mode tune --db data/experiment.sqlite3`
   ranks a `ridge_lambda x feature_window x player_decay` grid by
   walk-forward MAE and prints a ready-to-paste `model:` block. Use `--limit`
   (e.g. 60) for faster sweeps; early-season dates barely differentiate
   because training rows are sparse for every combo.
3. **Adopt a winner** by editing the `model:` section of the effective
   config — `config.local.yaml` when it exists (it shadows `config.yaml`),
   otherwise `config.yaml`. Production (`apply_opponent_model`), the weekly
   challenger, and the game backtest all read `model_ml.model_settings(cfg)`,
   so the new values apply to projections, week-game tiles, and lock/wait
   probabilities on the next publish — no code changes needed.
4. **Never force it**: if no config clearly beats defaults, keep them. If the
   ridge ever underperforms persistently, raising `min_train_rows` (e.g.
   `999999`) effectively disables the overlay and every decision reverts to
   B0 without a code change.

### Fixture Ingestion
```bash
# Load data/fixtures/<season>/{games,priors}.parquet into the experiment DB
.venv/bin/python scripts/ingest_fixtures_to_db.py --db data/experiment.sqlite3
```

### Vercel Serverless Lock Endpoint
- Production URL: `https://lock-in-model.vercel.app/api/lock`
- Reads current committed locks on `main`: `curl https://lock-in-model.vercel.app/api/lock`
- Local implementation: `api/lock.ts` (TypeScript ESM handler) and `shared/locks-core.cjs` (CommonJS mutation core).
