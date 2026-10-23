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
# 1. Python unit and regression tests (214 tests)
.venv/bin/python -m pytest -q

# 2. Code formatting check
.venv/bin/python -m black --check *.py tests

# 3. Node.js frontend policy & client logic tests (50 tests)
node --test tests/*.test.cjs
```

### Targeted Testing (Token & Time Saving)
When modifying a specific component, run its corresponding test file first:

| Subsystem Modified | Targeted Test Command |
| :--- | :--- |
| Core modeling & decisions | `.venv/bin/python -m pytest tests/test_core.py` |
| Positional lineup optimizer | `.venv/bin/python -m pytest tests/test_lineup.py` |
| Locked-player pinning & storage | `.venv/bin/python -m pytest tests/test_lineup_pinning.py` |
| Projections & Sleeper parsing | `.venv/bin/python -m pytest tests/test_projections.py` |
| Daily badges & leaderboards | `.venv/bin/python -m pytest tests/test_daily_badges.py tests/test_badge_awards.py` |
| Season badge store & ledger | `.venv/bin/python -m pytest tests/test_badge_store.py` |
| Season review aggregates | `.venv/bin/python -m pytest tests/test_season_review.py` |
| Pickups & schedule-aware swaps | `.venv/bin/python -m pytest tests/test_pickups.py` |
| SQLite game store | `.venv/bin/python -m pytest tests/test_game_store.py` |
| Evaluation harness | `.venv/bin/python -m pytest tests/test_evaluator.py` |
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
# Weekly lock-policy regret vs Oracle over a season's stored games
.venv/bin/python evaluator.py --mode weekly --season 2026-27 --db data/experiment.sqlite3

# Walk-forward game-forecast backtest: B0 production baseline vs CHALLENGER_C1
.venv/bin/python evaluator.py --mode game --season 2025-26 --db data/experiment.sqlite3
```
Policies: `B0` (production `decide.per_player_week_decision`), `RAW_NORMAL`,
`ALWAYS_WAIT`, `THRESHOLD_40`, `CHALLENGER_C1` (opponent-aware Ridge model),
`ORACLE`. `--policies` selects a subset, `--limit` caps player-weeks or slate
dates. `data/experiment.sqlite3` holds ingested Parquet fixtures for training;
never point these at `data/lockin.sqlite3`.

### Fixture Ingestion
```bash
# Load data/fixtures/<season>/{games,priors}.parquet into the experiment DB
.venv/bin/python scripts/ingest_fixtures_to_db.py --db data/experiment.sqlite3
```

### Vercel Serverless Lock Endpoint
- Production URL: `https://lock-in-model.vercel.app/api/lock`
- Reads current committed locks on `main`: `curl https://lock-in-model.vercel.app/api/lock`
- Local implementation: `api/lock.ts` (TypeScript ESM handler) and `shared/locks-core.cjs` (CommonJS mutation core).
