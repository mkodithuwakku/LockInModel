# Implementation Runbook: Epic 4 — Roster- & Slot-Aware Lock Decisions & Team Evaluation

**Branch:** `feature/roster-aware-locks` (create and switch to this dedicated git branch before making any code edits; do NOT work directly on `main`)  
**Status:** Implemented — all steps below landed on `feature/roster-aware-locks`; verification checklist passed  
**Reference Document:** `docs/epics/ROSTER_AWARE_LOCK_DECISIONS.md`  
**Python Runtime:** Always run `.venv/bin/python` from inside `LockInModel/`.

---

## 1. Token-Efficiency Rules for the Implementing Agent

To complete this epic with minimal token usage and zero wasted exploratory reads:
1. **Do NOT use broad codebase searches or read unrelated files** (`sleeper.py`, `badge_*.py`, `season_review.py`, `pickups.py`, `pages.py`, `web/style.css`).
2. **Exact lines to read before editing:**
   - `decide.py` (lines 1–166, whole file is 166 lines)
   - `lineup.py` (lines 13–101 for `SLOTS`, `eligible`, `optimal_assignment`; lines 381–415 for `lock_match`, `_pin_index`)
   - `engine.py` (lines 510–690 for where per-player decisions, Ridge tiles, projections, and `team_locks` come together)
   - `simulation.py` (lines 56–94 for how Test Week `banked` scores interact with `build_dashboard`)
   - `evaluator.py` (lines 168–409 for `simulate_weekly_lock` and `evaluate_season_weekly_policy`; lines 671–794 for CLI `main`)
   - `model_check.py` (lines 60–181 for `_live_sections` and `summarize`)
3. **Zero UI/CSS edits required:** The user explicitly requested that reasoning appear **only** inside the existing player modal (`#player-dialog` `.detail-reason`, which already renders `p.note || p.reason` at `web/app.js:966`). Do **not** edit `web/app.js`, `web/style.css`, or `pages.py` allowlists.

---

## 2. File Boundaries (What to Touch vs What NOT to Touch)

### Files to Modify
1. `decide.py`:
   - Add `apply_roster_lock_context(team, rows, locks=None)` (and helper functions for contender ceiling $E[M_j]$, beat probability $P(M_j \le c)$, and Hungarian marginal displaced contender $j^*$).
2. `engine.py`:
   - Call `apply_roster_lock_context(team, rows, locks=team_locks)` right after `row["projection"]` and `row["is_locked"]` are populated (just before `recommend_lineup()` at line ~667).
3. `simulation.py`:
   - In `report(run, provider)` (around line 61), if `banked` has entries, pass `banked` locks into `apply_roster_lock_context` so Test Week practice decisions also reflect remaining open starter slots as players get banked.
4. `evaluator.py`:
   - Add `TEAM_POLICIES = ("SOLO_B0", "ROSTER_B0", "SOLO_C1", "ROSTER_C1", "ALWAYS_WAIT", "THRESHOLD_40", "TEAM_ORACLE")`.
   - Add `simulate_team_weekly_locks(...)` and `evaluate_season_team_weekly_policy(...)`.
   - Add `--mode team-weekly` to CLI `main()` and `_print_team_weekly_table()`.
5. `model_check.py`:
   - Add `team_weekly` summary under `_live_sections()` and `summarize()` so biweekly checks report `ROSTER_C1` / `ROSTER_B0` vs `SOLO_C1` / `SOLO_B0`.
6. `tests/test_core.py` & `tests/test_evaluator.py`:
   - Add unit tests for Sasser vs. Luka slot contention, 0-remaining-games contention, open `UTIL` non-contention, and `simulate_team_weekly_locks` regret comparison.
7. `README.md`, `docs/MODEL.md`, `docs/agents/ARCHITECTURE_MAP.md`, `docs/epics/MODEL_EVALUATION.md`, `docs/epics/ROSTER_AWARE_LOCK_DECISIONS.md`:
   - Update documentation to reflect implemented behavior.

### Files NOT to Modify
- Do NOT touch `web/app.js`, `web/style.css`, `web/insights.js`, `web/pages.js`, or `pages.py`.
- Do NOT break existing solo `per_player_week_decision()` callers or `simulate_weekly_lock()` signatures.

---

## 3. Step-by-Step Implementation Blueprint

### Step 1: Implement `apply_roster_lock_context` in `decide.py`

Import `active_slots`, `eligible`, `optimal_assignment`, `lock_match`, `_pin_index`, `RESERVE`, `OUT` from `lineup` (or pass/import cleanly without circular import issues).

#### 1.1 Contender Distribution Helpers
```python
from math import erf, exp, pi, sqrt

def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))

def _contender_future_mus(row: dict, reference=None) -> list[float]:
    """Extract per-game projected means for remaining unplayed games this week."""
    rem = row.get("remaining_games_est")
    if not isinstance(rem, (int, np.integer)) or rem <= 0:
        return []
    last_date = str(row.get("last_game_date") or "")
    fallback_mu = (
        (row.get("projection") or {}).get("projected_fp")
        if isinstance(row.get("projection"), dict)
        else None
    )
    if fallback_mu is None or not np.isfinite(fallback_mu):
        fallback_mu = row.get("fp_mean_recent")
    if fallback_mu is None or not np.isfinite(fallback_mu):
        return []
    fallback_mu = float(fallback_mu)

    future_games = sorted(
        (
            g
            for g in (row.get("week_games") or [])
            if g.get("status") in ("pre_game", "scheduled")
            and (not last_date or str(g.get("date") or "") > last_date)
        ),
        key=lambda g: str(g.get("date") or ""),
    )
    mus = []
    for g in future_games[: int(rem)]:
        val = g.get("proj_fp")
        mus.append(float(val) if isinstance(val, (int, float)) and np.isfinite(val) else fallback_mu)
    if len(mus) < int(rem):
        mus.extend([fallback_mu] * (int(rem) - len(mus)))
    return mus

def _prob_contender_le(target_fp: float, current_fp, future_mus: list[float], sigma: float) -> float:
    """P(contender's best weekly score <= target_fp)."""
    if current_fp is not None and np.isfinite(current_fp) and float(current_fp) > target_fp:
        return 0.0
    if not future_mus:
        return 1.0
    sd = max(float(sigma) if sigma is not None and np.isfinite(sigma) else 4.0, 4.0)
    p = 1.0
    for mu in future_mus:
        p *= _norm_cdf((target_fp - float(mu)) / sd)
    return float(np.clip(p, 0.0, 1.0))

def _expected_contender_max(current_fp, future_mus: list[float], sigma: float) -> float:
    """Expected best weekly score E[max(current_fp, X_1, ..., X_k)] via numerical integration."""
    has_curr = current_fp is not None and np.isfinite(current_fp)
    c_val = float(current_fp) if has_curr else float("-inf")
    if not future_mus:
        return c_val
    sd = max(float(sigma) if sigma is not None and np.isfinite(sigma) else 4.0, 4.0)
    lo = min([m - 5.0 * sd for m in future_mus] + ([c_val] if has_curr else []))
    hi = max([m + 5.0 * sd for m in future_mus] + ([c_val] if has_curr else []))
    # 64-point midpoint rule over [lo, hi]: fast, exact for smooth normal CDF product
    steps = 64
    dx = (hi - lo) / steps
    # E[M] = c_val_floor + integral_{c_val}^{hi} (1 - F_M(x)) dx (or integration by parts over [lo, hi])
    start_x = max(lo, c_val) if has_curr else lo
    if start_x >= hi:
        return c_val
    dx = (hi - start_x) / steps
    integral = 0.0
    for step in range(steps):
        x = start_x + (step + 0.5) * dx
        cdf = 1.0
        for mu in future_mus:
            cdf *= _norm_cdf((x - float(mu)) / sd)
        integral += (1.0 - cdf) * dx
    return float(start_x + integral)
```

#### 1.2 Slot Pinning & Hungarian Marginal Challenger
In `apply_roster_lock_context(team, rows, locks=None)`:
1. Call `slots = active_slots(team)`. If not `slots`: return `rows`.
2. Resolve pinned slots from `locks` (handling both `state/locks.json` dict records and Test Week `banked` dicts where key is player name):
   - Any row with `row.get("is_locked")` or `row.get("banked")` or matching a `locks` record pins its corresponding slot via `_pin_index` (or first matching unpinned slot for `row.get("roster_slot")` / eligible slot).
   - Let `open_slots = [s for idx, s in enumerate(slots) if idx not in pinned_indices]`.
3. Build contender profiles for all non-pinned rows not in `RESERVE` (`{"IR", "TAXI"}`) and whose injury status is not in `OUT`:
   - Compute `future_mus = _contender_future_mus(row)`, `curr_fp = row.get("last_game_fp") if row.get("decision") in ("LOCK", "WAIT") else None`, `sigma = row.get("fp_std_recent") or 4.0`, and `expected_max = _expected_contender_max(curr_fp, future_mus, sigma)`.
4. For each candidate `row_i` where `row_i.get("decision") in ("LOCK", "WAIT")` and `row_i.get("last_game_fp") is not None` and not `row_i.get("is_locked")`:
   - Save `row_i["p_lock_solo"] = row_i["p_lock"]` and `row_i["decision_solo"] = row_i["decision"]`.
   - Find distinct slot names `s` in `open_slots` where `eligible(row_i.get("positions"), s)` is True.
   - If no eligible slot exists in `open_slots`:
     - Update `row_i`: `p_lock = 0.0`, `p_wait = 1.0`, `decision = "WAIT"`, `status = "WAIT"`, `reason = f"All eligible lineup slots ({'/'.join(row_i.get('positions') or ['slot'])}) are already pinned this week."`
     - Continue.
   - Let `other_contenders` be all valid contenders $j \ne i$ with `expected_max > -inf`, formatted for `optimal_assignment` as `{"index": j, "positions": row_j.get("positions", []), "projected_fp": max(0.0, expected_max)}`.
   - Run `base_assign = optimal_assignment(open_slots, other_contenders)` and let `base_chosen = {other_contenders[k]["index"] for k in base_assign if k is not None}`.
   - For each distinct eligible slot `s`:
     - Remove one occurrence of `s` from `open_slots` $\to$ `reduced_slots`.
     - Run `red_assign = optimal_assignment(reduced_slots, other_contenders)`.
     - Compute total assigned `projected_fp` and pick the slot `best_slot` that maximizes the remaining others' total FP.
   - Let `best_chosen = {other_contenders[k]["index"] for k in best_red_assign if k is not None}`.
   - Displaced set: `displaced = base_chosen - best_chosen`.
   - If `not displaced`:
     - No contender is displaced (an open slot is freely available for `row_i`).
     - However, check if `row_i` itself was even in the top open slots if `row_i` has 0 remaining games? Wait: if `not displaced`, there is a vacant eligible slot even after seating all other contenders, so `row_i` does not block anyone! Keep `p_contender_le = 1.0`, `challenger = None`.
   - If `displaced`:
     - Let `j_star` be the displaced contender (if multiple due to ties, pick the one with highest `expected_max`).
     - Compute `p_contender_le = _prob_contender_le(float(row_i["last_game_fp"]), curr_fp_j, future_mus_j, sigma_j)`.
   - Compute `p_lock_team = float(np.clip(row_i["p_lock_solo"] * p_contender_le, 0.0, 1.0))`.
   - Update `row_i["p_lock"] = p_lock_team`, `row_i["p_wait"] = float(1.0 - p_lock_team)`, `row_i["decision"] = "LOCK" if p_lock_team >= 0.5 else "WAIT"`, `row_i["status"] = row_i["decision"]`.
   - Format `row_i["reason"]` clearly:
     - If `challenger` caused or reinforced `WAIT` (`row_i["decision"] == "WAIT"` and `p_contender_le < 0.65`):
       - Include challenger's name, their projected per-game mean (or already-scored FP if higher), their remaining games count, and `best_slot`.
       - Example: `"Latest score 28.0 FP vs baseline 18.0 (1 remaining); wait for Luka Dončić (58.0 proj FP, 2 remaining) contesting PG."`

---

### Step 2: Wire `apply_roster_lock_context` into `engine.py` and `simulation.py`

1. In `engine.py`:
   - Right after `team_locks` are applied to `rows` (around line 666, before `daily_lineup = recommend_lineup(...)`), call:
     ```python
     if not team.get("unsupported_scoring") and not getattr(provider, "stats_error", None):
         apply_roster_lock_context(team, rows, locks=team_locks)
     ```
2. In `simulation.py`:
   - In `report(run, provider)` (around line 69), after `banked = run["locks"].get(team["id"], {})` is retrieved, convert `banked` into lock records (or pass `banked` to `apply_roster_lock_context(team, team["results"], locks=banked)`) before marking banked rows as `status="BANKED"`, and recompute the summary lock/wait counts if needed.

---

### Step 3: Add Team-Slot Weekly Evaluator in `evaluator.py` & `model_check.py`

1. In `evaluator.py`:
   - Add `TEAM_POLICIES = ("SOLO_B0", "ROSTER_B0", "SOLO_C1", "ROSTER_C1", "ALWAYS_WAIT", "THRESHOLD_40", "TEAM_ORACLE")`.
   - Implement `simulate_team_weekly_locks(team_games, slots, weights, cfg, policy="ROSTER_B0", week_start=None, previous_games=None, positions=None, context=None)`:
     - `team_games`: DataFrame of games for all players on the team roster.
     - `slots`: list of active slot strings, e.g. `["PG", "SG", "G", "SF", "PF", "F", "C", "UTIL", "UTIL", "UTIL"]`.
     - `positions`: dict mapping `player_id -> list[str]` or primary position string (e.g. `"PG"` or `["PG", "SG"]`).
     - For `TEAM_ORACLE`: for each roster player who played in `[start, end]`, take their best single game $\max_g \text{FP}_{p,g}$, and run `optimal_assignment(slots, candidates)` to get `oracle_fp`.
     - For sequential policies (`SOLO_B0`, `ROSTER_B0`, `SOLO_C1`, `ROSTER_C1`, `ALWAYS_WAIT`, `THRESHOLD_40`):
       - Iterate over each day $d$ in the Monday–Sunday week where at least one unlocked roster player played a game.
       - For each active unlocked roster player, build their as-of-day-$d$ decision row (calling `per_player_week_decision` with observations $\le d$, `remaining_games` in the week after $d$, and `future_mus` from C1 Ridge if `policy in ("SOLO_C1", "ROSTER_C1")`).
       - If `policy in ("ROSTER_B0", "ROSTER_C1")`, run `apply_roster_lock_context` across the team rows with the currently pinned `open_slots`.
       - For players who played on day $d$ and whose resulting decision is `"LOCK"`, sort them by `(p_lock, last_game_fp)` descending and pin each into the best available eligible slot in `open_slots` (using the same marginal-slot selection so flexible players leave specialized slots open when possible).
       - At week end, any remaining unpinned slots in `open_slots` are filled via `optimal_assignment` using the final game of the week (`week.iloc[-1].FP`) of each still-unlocked player who played at least once that week.
       - Return `total_fp`, `oracle_fp`, `regret = round(oracle_fp - total_fp, 2)`, `efficiency`, `locked_count`, and `decisions`.
   - Implement `evaluate_season_team_weekly_policy(season, game_store, cfg, weights, policies=None, history=None, positions=None, limit=None)`:
     - Group active players in each week into deterministic balanced multi-position rosters (e.g., partitioning the active players of that week into 10-player rosters matching standard positional eligibility `PG, SG, SF, PF, C`, or using `cfg["teams"]` if all players exist in the store) and run `simulate_team_weekly_locks` across all policies.
   - Add `"team-weekly"` to `--mode` choices in `evaluator.py` `main()`.
2. In `model_check.py`:
   - In `_live_sections()`, also run `evaluator.evaluate_season_team_weekly_policy(..., policies=["SOLO_B0", "ROSTER_B0", "SOLO_C1", "ROSTER_C1", "TEAM_ORACLE"])` and include `"team_weekly"` in the returned dict.

---

## 4. Verification Checklist

Run these commands from `LockInModel/` before completing:
```bash
# 1. Targeted unit tests first
.venv/bin/python -m pytest tests/test_core.py tests/test_evaluator.py tests/test_lineup.py -q

# 2. Full Python test suite
.venv/bin/python -m pytest -q

# 3. Black formatting check
.venv/bin/python -m black --check *.py tests

# 4. Node.js frontend test suite
node --test tests/*.test.cjs
```
