# Epic proposal: roster- and slot-aware lock/wait decisions

**Status:** implemented and merged to `main` (developed on `feature/roster-aware-locks`, commit `2676e9b`) — Stage 2 slot-contention pass in `decide.py` (`apply_roster_lock_context`), wired into `engine.py` and `simulation.py`, modal-only reasoning via `row["reason"]`, and `--mode team-weekly` in `evaluator.py` plus `team_weekly` reporting in `model_check.py`.  
**Prepared:** October 23, 2026.  
**Target branch:** `feature/roster-aware-locks` (merged into `main`).  
**Implementation runbook:** [`docs/runbooks/ROSTER_AWARE_LOCK_DECISIONS.md`](../runbooks/ROSTER_AWARE_LOCK_DECISIONS.md).

---

## 1. Problem statement and outcome

### 1.1 The problem
Until now, `decide.py` (`per_player_week_decision`) and `model.py` (`lock_recommendation`) have evaluated every player in complete isolation—comparing a player's latest score $c_i$ only against *that same player's* remaining games ($\mu_{i,m}, \sigma_i$).

Consider a concrete scenario:
- A manager rosters **Marcus Sasser** (`PG`, role player averaging ~18 FP, playing Wednesday and Sunday) and **Luka Dončić** (`PG`, MVP candidate averaging ~58 FP, playing Thursday and Saturday).
- On Wednesday night, Sasser scores **28.0 FP**.
- On Thursday morning, the solo model computes $P(\text{Sasser's Sunday game} \le 28.0) \approx 0.92$ and recommends **`LOCK`**.
- However, in Sleeper Lock-In mode, locking Sasser permanently freezes him into an active slot (`PG`, `G`, or `UTIL`) for the rest of the week. If `PG` (and any flexible `G`/`UTIL` fallback) is contested by Luka Dončić or other higher-upside teammates with remaining games, locking Sasser's 28.0 FP blocks a ~58.0 FP star from occupying that slot—or forces a higher-projected teammate out of `UTIL`.
- Even worse, on Sasser's final game of the week (`remaining_games_est == 0`), the solo model sets `p_lock = 1.0` (`LOCK`) unconditionally, even if a star teammate still has an upcoming game tonight for that same open slot.

Conversely, if the roster has enough open eligible slots (`PG`, `G`, `UTIL`) that both Sasser and Luka can be accommodated without displacing a stronger contender, Sasser should only be judged against his own remaining games and the actual **marginal displaced contender** at the bottom of the eligible slot chain.

### 1.2 The evaluation blind spot
In `evaluator.py`, `simulate_weekly_lock()` and `evaluate_season_weekly_policy()` currently replay each `(PLAYER_ID, WEEK)` independently. In a solo-player replay, locking Sasser's 28.0 FP when he scores 18.0 FP on Sunday achieves **0 solo regret**, completely ignoring the **30.0 FP team regret** caused by blocking Luka Dončić's 58.0 FP game from the `PG` slot.

### 1.3 Desired outcomes
1. **Two-stage Lock/Wait model:**
   - **Stage 1 (Solo Baseline):** Preserve `per_player_week_decision()` for personal baseline ($\mu_i, \sigma_i$), rarity boost, and solo lock probability $p_{\text{lock, solo}}(i)$.
   - **Stage 2 (Roster & Slot Contention Pass):** Evaluate open unpinned league slots (`active_slots(team)` minus `state/locks.json` and Test Week `banked` slots) using the Hungarian maximum-weight solver (`optimal_assignment`). Adjust $p_{\text{lock}}(i)$ by the probability that locking player $i$ into an eligible slot does not displace a higher-upside contender's remaining weekly distribution.
2. **Modal-only explanation (`row["reason"]`):**
   - Keep the roster sheet quick-view (`.player-row`) visually untouched—no extra badges, tags, or layout changes.
   - Surface clear, specific contention reasoning inside `row["reason"]`, which renders in `#player-dialog` (`.detail-reason`) when a user clicks a player card.
3. **Team-slot weekly lock evaluation (`--mode team-weekly`):**
   - Preserve existing per-game (`--mode game`, `--mode tune`) and solo weekly (`--mode weekly`) scorecards.
   - Add `simulate_team_weekly_locks()` and `evaluate_season_team_weekly_policy()` to `evaluator.py` (and `model_check.py`) to measure slot-constrained team total FP and regret against `TEAM_ORACLE`.

---

## 2. Mathematical & algorithmic specification

### 2.1 Open slot resolution
Given a team configuration and active lock records (`team_locks` in live mode or `banked` in Test Week):
1. Extract `slots = active_slots(team)` (`PG`, `SG`, `G`, `SF`, `PF`, `F`, `C`, `UTIL`).
2. Identify pinned slot indices using `_pin_index` / `lock_match` (from `lineup.py`).
3. Let $S_{\text{open}}$ be the list of unpinned active slots. If `slots is None` or empty, Stage 2 is a no-op and Stage 1 decisions stand.

### 2.2 Weekly contender distribution per active roster player
For every roster player $j$ not already pinned/locked, not in `RESERVE` (`IR`, `TAXI`), and not in `OUT`:
- Let $c_j$ be player $j$'s latest completed unlocked score this week (`last_game_fp` if finite and `status in ("LOCK", "WAIT")`, else $-\infty$).
- Let $\mu_{j,1}, \dots, \mu_{j,k_j}$ be the per-game means for player $j$'s remaining unplayed games this week (`week_games` with `status in ("pre_game", "scheduled")` after the decision cutoff, using `game["proj_fp"]` $\to$ `projection["projected_fp"]` $\to$ `fp_mean_recent`). If `week_games` is unavailable but `remaining_games_est > 0`, repeat `projected_fp` or `fp_mean_recent` `remaining_games_est` times.
- Let $\sigma_j = \max(\text{fp\_std\_recent}, 4.0)$.
- For any target score $c$, the probability that contender $j$'s best weekly score $M_j$ stays at or below $c$ is:
  $$P(M_j \le c) = \mathbb{I}(c_j \le c) \times \prod_{m=1}^{k_j} \Phi\left(\frac{c - \mu_{j,m}}{\sigma_j}\right)$$
- Define contender $j$'s expected weekly ceiling $E[M_j]$ via numerical Gauss-Hermite / grid integration or exact normal order-statistic approximation over $\{c_j\} \cup \{\text{Normal}(\mu_{j,m}, \sigma_j)\}_{m=1}^{k_j}$:
  - For $k_j = 0$: $E[M_j] = c_j$ (if finite).
  - For $k_j \ge 1$: compute $\mathbb{E}[\max(c_j, X_1, \dots, X_{k_j})]$ where $X_m \sim \mathcal{N}(\mu_{j,m}, \sigma_j^2)$, e.g. via deterministic 1D quadrature $\int_{-\infty}^{\infty} x \, dF_{\max}(x)$ or $\mu_{\max} + \sigma_j \, \phi(\dots)$, so that multi-game stars properly reflect their best-of-$k_j$ expectation.

### 2.3 Marginal slot contention via Hungarian assignment
For a candidate player $i$ with completed score $c_i$ (`last_game_fp` is finite and Stage 1 `decision in ("LOCK", "WAIT")`):
1. Find all distinct slot types $s \in S_{\text{open}}$ where `eligible(row_i["positions"], s)` is True.
   - If **no** open slot in $S_{\text{open}}$ is eligible for player $i$, player $i$ has nowhere to lock: set `p_lock = 0.0`, `p_wait = 1.0`, `decision = "WAIT"`, `status = "WAIT"`, and explain in `reason` that all eligible slots are already pinned.
2. Let $C_{-i}$ be the pool of all other active contender players $j \ne i$ who have at least one completed game or remaining game this week ($E[M_j] > -\infty$), weighted by `projected_fp = E[M_j]`.
3. Solve the baseline assignment over all open slots without player $i$:
   - Let $A_0 = \text{optimal\_assignment}(S_{\text{open}}, C_{-i})$, and let $U_0 \subseteq C_{-i}$ be the set of contenders assigned to a slot in $A_0$, with total expected value $W_0 = \sum_{j \in U_0} E[M_j]$.
4. For each unique eligible slot type $s \in S_{\text{open}}$ for player $i$, remove one instance of $s$ to form $S_{\text{open}}^{(-s)}$:
   - Solve $A_s = \text{optimal\_assignment}(S_{\text{open}}^{(-s)}, C_{-i})$ with total value $W_s$.
   - Choose the slot $s^*$ that maximizes $W_s$ (minimizing the opportunity cost $\Delta_i = W_0 - W_{s^*}$).
   - Identify the **displaced contender** $j^*$:
     - Specifically, $U_0 \setminus U_{s^*}$ (where $U_{s^*}$ is the set of contenders assigned in $A_{s^*}$) contains at most one player $j^*$ by matroid / augmenting-path properties of maximum-weight bipartite matching!
     - If $U_0 \setminus U_{s^*}$ is empty (meaning there were more open eligible slots than contenders, so locking player $i$ into $s^*$ displaces nobody), then there is **no marginal contender** ($P(M_{j^*} \le c_i) = 1.0$).
     - If $U_0 \setminus U_{s^*} = \{j^*\}$, then locking player $i$ into $s^*$ directly forces contender $j^*$ out of the starting lineup.
5. Compute the team-adjusted lock score:
   $$p_{\text{lock, team}}(i) = p_{\text{lock, solo}}(i) \times P(M_{j^*} \le c_i)$$
   - Set `p_lock = float(np.clip(p_lock_team, 0.0, 1.0))` and `p_wait = float(1.0 - p_lock)`.
   - Set `decision = "LOCK" if p_lock >= 0.5 else "WAIT"` and `status = decision`.

---

## 3. Modal reasoning contract (`row["reason"]`)

The roster sheet quick-view (`.player-row`) is **not** modified. All reasoning lives in `row["reason"]` (displayed in `#player-dialog` `.detail-reason`):

- **Flipped or held to `WAIT` by slot contention ($P(M_{j^*} \le c_i)$ decisive):**
  - `"Latest score {c_i:.1f} FP vs {mu_i:.1f} baseline ({rem} remaining); wait for {j_name} ({j_proj:.1f} proj FP, {j_rem} remaining) contesting {slot}."`
  - If `j_rem == 0` and $j^*$ already scored $c_{j^*} > c_i$: `"Latest score {c_i:.1f} FP trails unlocked contender {j_name} ({c_j:.1f} FP) for {slot}."`
- **`WAIT` primarily due to player $i$'s own remaining games:**
  - `"Latest score {c_i:.1f} FP versus baseline {mu_i:.1f}; {rem} remaining opportunities."`
- **`LOCK` with remaining games:**
  - If a marginal contender $j^*$ existed and was cleared: `"Latest score {c_i:.1f} FP versus baseline {mu_i:.1f} ({rem} remaining) clears {slot} contender {j_name}."`
  - If uncontested: `"Latest score {c_i:.1f} FP versus baseline {mu_i:.1f}; {rem} remaining opportunities."`
- **`LOCK` with 0 remaining games (uncontested or beats $j^*$):**
  - `"No further team games in the verified week."` (or with contender context if contested and cleared).
