# Project instructions

These instructions apply to the entire repository.

## Keep the README current

Treat `README.md` as a living, portfolio-quality walkthrough of the implemented
project. Review it for every code, dependency, configuration, or workflow change.
Update affected sections in the same change; documentation is part of completion,
not a separate follow-up task.

- Keep features, architecture, API/data flow, persistence, scoring/model behavior,
  setup commands, configuration, tests, and limitations consistent with the code.
- Update linked guides in `docs/` when their details change. Avoid conflicting
  descriptions between the README and those guides.
- When the visible workflow changes, refresh affected screenshots in
  `docs/screenshots/`. If a replacement cannot be captured, remove or clearly label
  the outdated image and document the screen/state that needs capturing.
- Preserve the short recruiter overview and technical interview material:
  meaningful decisions, tradeoffs, challenges, and a concrete implementation deep dive.
- Verify claims against source files and configuration. Distinguish implemented,
  tested, and planned behavior. Do not invent personal motivation, ownership history,
  measured accuracy, performance, deployment, or security guarantees.
- Preserve model/replay limitations and data provenance. Lock scores and pickup
  scores are heuristics; a working replay does not establish predictive accuracy.
- Never include credentials, private configuration, or personal account details in
  documentation or screenshots.

Before finishing, check local Markdown links and referenced files, validate changed
commands where practical, and run checks appropriate to the code change. Summarize
documentation updates and validation in the handoff. If a change has no effect
on documented behavior, explain that briefly instead of adding a meaningless
README edit. Documentation-only changes do not require new application tests.

These instructions govern future work in this repository; they do not create a
background README generator or scheduled task.

## Roster-first interface

The roster sheet is the primary UI on desktop and mobile. Keep it first in the
main content, immediately after compact team selection and essential controls.
Recommended players and positions belong in the sheet. Team counters, insights,
explanatory copy, and decorative elements must not displace it above the fold.
Keep the header compact; put supporting panels below the complete roster.
Validate this hierarchy at phone and desktop widths when changing the layout.

Use a charcoal base with a subtle plum undertone and muted purple accents.
Reserve soft gold for small details; avoid yellow highlights and saturated plum
across large application surfaces.

## Agent quick context & token efficiency

To maximize agent effectiveness and minimize unnecessary token expenditure:
- **Python Runtime:** Always use `.venv/bin/python` from the `LockInModel/` directory. System Python or Anaconda Python will fail due to missing dependencies (`nba_api`, `pytest`, etc.).
- **Detailed Agent Maps:**
  - Architecture, modules, and SQLite schemas: `docs/agents/ARCHITECTURE_MAP.md`
  - Test suites, verification commands, and workflows: `docs/agents/WORKFLOWS_AND_TESTING.md`

### Where to look (file routing)

Do not read entire multi-thousand line files speculatively. Consult this index:
- **Lock / Wait decision heuristics:** `decide.py`, `model.py`
- **Locked-player pinning & state:** `state/locks.json`, `storage.py` (`load_locks`), `lineup.py` (`recommend_lineup`)
- **Vercel lock endpoint & shared logic:** `api/lock.ts`, `shared/locks-core.cjs`
- **Prior-season history blending (<10 games):** `season_history.py`
- **Daily lineup optimizer & off-day filling:** `lineup.py`, `web/insights.js` (`repinLineup`)
- **External Sleeper forecasts & Poisson bonuses:** `projections.py`
- **Daily badges (15 stat + 4 fantasy leaders):** `daily_badges.py`
- **Milestones & contextual awards (Butterfingers, streaks):** `badge_awards.py`
- **Season badge ledger in SQLite:** `badge_store.py`
- **Season Review aggregations & key players:** `season_review.py`
- **Waiver pickups & schedule-aware swap cards:** `pickups.py` (`find_pickups`, `suggest_swap`)
- **Games to watch cross-team matchup ranking:** `web/insights.js` (`gamesToWatch`), `web/app.js`
- **Sleeper import & fallback box scores:** `sleeper.py`, `sleeper_stats.py`
- **SQLite game persistence & upserts:** `game_store.py`, `forecast_store.py`
- **Schedule caching & remaining games:** `schedule.py`
- **Static export & daily GitHub Pages publication:** `pages.py`, `publication.py`
- **Offline Test Week practice simulator:** `simulation.py`
- **Client-side presentation, derived form, & views:** `web/insights.js`, `web/app.js`

### Verification commands

```bash
# Run before completing any code change:
.venv/bin/python -m pytest -q
.venv/bin/python -m black --check *.py tests
node --test tests/*.test.cjs
```

