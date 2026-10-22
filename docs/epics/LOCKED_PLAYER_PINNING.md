# Epic proposal: locked-player pinning for daily recommended lineups

**Status:** proposed; planning and implementation specification only. No code or serverless infrastructure is implemented by this document.

**Prepared:** October 22, 2026.

**Reviewed baseline:** source commit `7952a4e`.

**Development boundary:** this specification defines the data model, serverless write bridge, optimizer adjustments, client-side re-pinning, and verification requirements. Implementation must follow this spec on a dedicated feature branch (`feature/locked-player-pinning`), verify offline with the existing test runner, and preserve the repository's roster-first UI and static hosting boundaries.

---

## 1. Problem statement and outcome

### 1.1 The problem
LockIn assists managers in Sleeper fantasy basketball leagues configured in "lock-in" mode (`settings.game_mode == 1`). In this format, one performance per starter slot counts toward the weekly matchup. Once a manager chooses to lock a completed game, that player is permanently frozen in their current lineup slot for the remainder of that fantasy week: they cannot be benched, moved to another position, or used in subsequent games that week.

Currently, `lineup.py`'s `recommend_lineup()` computes the daily recommended lineup by solving a maximum-weight assignment using the Hungarian algorithm (`optimal_assignment()`) over all active roster players with a verified game that day. Because LockIn has historically lacked awareness of locked players, the optimizer may:
1. Reassign a locked starter to a different position (e.g. moving a locked PG to G or UTIL to free PG for another player).
2. Bench a locked player on an off-day and attempt to start an unlocked bench player in that slot.

Both actions are **strictly forbidden by Sleeper's rules**. Displaying an impossible lineup erodes trust and frustrates decision-making.

### 1.2 The desired outcome
When a player is flagged as locked for the active fantasy week:
- The player is **pinned** into their designated lineup slot.
- That slot is removed from the optimizer's candidate pool and cannot be reassigned to any other player.
- The pinned slot displays as banked/locked with its actual score rather than an upcoming projection.
- Remaining eligible roster players optimize exclusively across the remaining unpinned slots.
- Managers can toggle lock status directly from their phone on the published static website, with immediate optimistic feedback in the UI and durable persistence to the repository via a lightweight serverless endpoint.
- The Mac's morning publication job automatically pulls these flags from `main` and incorporates them into the authoritative daily report.

---

## 2. Established facts and system boundaries

The following constraints are verified against the live Sleeper API and LockIn codebase and are not open for debate:

1. **Sleeper API exposes no lock flag:**
   - `/league/{id}/rosters` returns `metadata` (push-notification preferences only, e.g. `allow_pn_*`) and `player_map` (`null`). No lock status field exists.
   - `/league/{id}/matchups/{week}` provides `players_points`, `starters_points`, `points`, and `starters`. These represent cumulative counted fantasy points, not lock flags. Bench players frequently possess non-zero `players_points`, confirming it is not a lock marker.
2. **Current starter slot is the locked slot:**
   - Sleeper blocks any movement of a locked starter. Consequently, a locked player's current `roster_slot` (derived from the `starters` array order in `player_meta`) **is** their locked slot. No position picker UI is needed—only a boolean per-player lock toggle.
3. **Partial auto-detection is mathematically possible:**
   - If a starter's `players_points` matches an *earlier* completed game's league-scored FP rather than their *latest* completed game's FP, the manager definitively locked the earlier game. If the score matches the latest game, lock status remains indistinguishable without manager input.
4. **GitHub Pages is read-only:**
   - The public website served from GitHub Pages is entirely static. No writes can be made directly to the web server.
5. **Local Flask is loopback-only and sleep-prone:**
   - The Mac running `app.py` binds to `127.0.0.1:8765`, is inaccessible over the public internet, and sleeps at night when managers watch games and make lock decisions. Flagging must work independently of the Mac's wake state.

### Explicit non-goals
- **No transaction or lock submission to Sleeper:** LockIn remains read-only with respect to Sleeper. The manager makes the real lock decision inside the official Sleeper mobile app.
- **No weekly dynamic programming solver:** This feature enforces positional constraints; it does not replace the statistical heuristics in `decide.py` or solve a multi-day stochastic stopping problem.
- **Test Week and non-Sleeper teams out of scope:** Offline Test Week already possesses its own isolated morning/night banking mechanism in `state/test-week.json`. Local practice teams and Test Week will not integrate with `locks.json` or the Vercel bridge.

---

## 3. User stories and operational workflows

### Story 1: Night-time lock on phone (manager workflow)
> *As a manager watching Thursday night basketball, I lock a 52 FP performance from my starting Point Guard in the Sleeper app. I open LockIn on my iPhone, locate my PG in the roster sheet, and tap the lock icon. I enter my personal passcode once. The UI instantly updates: the PG is pinned to the PG slot, showing 52 FP (banked). Tomorrow’s recommended lineup immediately re-optimizes client-side, confirming that my other guards will flex into SG and G without displacing my locked PG. A background POST to the serverless endpoint persists this lock to GitHub.*

### Story 2: Morning scheduled publication (Mac workflow)
> *At 7:00 AM America/Edmonton, the Mac's LaunchAgent triggers `publication.py`. Before running analysis, the script pulls the latest commits on `main` from GitHub, receiving the Thursday night `state/locks.json` update. The engine loads the locks, validates that the schedule week matches, pins the locked players in `recommend_lineup()`, and publishes the static report to GitHub Pages. When I wake up, the published report reflects my pinned lineup.*

---

## 4. Architecture and data contracts

```
[Phone Browser (Published Site)]
      │
      ├─ 1. User taps lock toggle on roster row
      ├─ 2. Client re-pins lineup optimistically in web/insights.js
      └─ 3. HTTPS POST (JSON + x-lockin-passcode)
            │
            ▼
[Vercel Serverless Function] (`api/lock.ts`)
      │
      ├─ 4. Validates passcode against process.env.LOCKIN_PASSCODE
      ├─ 5. Fetches state/locks.json from GitHub API (branch: main)
      ├─ 6. Updates/removes lock record with optimistic concurrency (SHA)
      └─ 7. Commits updated state/locks.json directly to main
            │
            ▼
[GitHub Repository] (`main` branch)
      │
      ▲ (7:00 AM LaunchAgent or manual publish)
      │
[Local Mac Pipeline] (`publication.py`)
      ├─ 8. git pull --ff-only origin main
      ├─ 9. engine.py reads state/locks.json
      ├─ 10. lineup.py pins slots before Hungarian solver
      └─ 11. pages.py exports public report to gh-pages branch
```

### 4.1 Data model: `state/locks.json`

The persistent file lives at `state/locks.json` on the `main` branch. It is checked into Git so changes made from the phone persist across checkouts and environments.

```json
{
  "$schema": "https://lockin.internal/schemas/locks-v1.json",
  "version": 1,
  "updated_at": "2026-10-22T23:15:00Z",
  "leagues": {
    "112233445566778899": {
      "schedule_week": 1,
      "locks": {
        "8145": {
          "player_id": "8145",
          "player_name": "Tyrese Haliburton",
          "canonical_name": "tyrese haliburton",
          "roster_slot": "PG",
          "slot_index": 0,
          "locked_at": "2026-10-22T23:14:58Z",
          "locked_fp": 54.5,
          "game_date": "2026-10-22"
        }
      }
    }
  }
}
```

#### Field specifications:
- `version` (`integer`): Schema version (initially `1`).
- `leagues` (`object`): Map of Sleeper `league_id` string to league lock container.
- `schedule_week` (`integer`): Active NBA fantasy week (e.g. 1 through 24).
- `locks` (`object`): Map of player identity key (Sleeper `player_id` preferred, lowercase canonical name fallback) to lock details.
- `roster_slot` (`string`): The assigned starter slot name (e.g. `PG`, `SG`, `SF`, `PF`, `C`, `G`, `F`, `UTIL`).
- `slot_index` (`integer`): Zero-based index within the team's ordered `starters` array to eliminate ambiguity when duplicate slots exist (e.g. two `UTIL` slots).
- `locked_fp` (`number | null`): Observed fantasy points in the locked performance, if known.
- `game_date` (`string | null`): ISO date (`YYYY-MM-DD`) of the locked game.

#### Expiry semantics:
Locks are scoped strictly to `schedule_week`. When the schedule week advances (e.g. from Week 1 to Week 2):
1. Any lock record whose `schedule_week` does not match the active week is **ignored by the engine**.
2. During the next write or sync, the store purges expired week records.
3. Locks never carry over across fantasy weeks.

---

## 5. Serverless write endpoint contract (Vercel)

A single Vercel TypeScript function located at `api/lock.ts` handles remote writes.

### 5.1 Endpoint specification
- **Method:** `POST`
- **Path:** `/api/lock`
- **Headers:**
  - `Content-Type: application/json`
  - `x-lockin-passcode: <shared_passcode>`

### 5.2 Request payload
```json
{
  "league_id": "112233445566778899",
  "schedule_week": 1,
  "action": "lock",
  "player": {
    "player_id": "8145",
    "player_name": "Tyrese Haliburton",
    "roster_slot": "PG",
    "slot_index": 0,
    "locked_fp": 54.5,
    "game_date": "2026-10-22"
  }
}
```
*For unlocking:* Set `"action": "unlock"`. The `player` object requires only `player_id` (or `player_name`).

### 5.3 Response contract
- `200 OK`:
  ```json
  {
    "status": "ok",
    "action": "lock",
    "player_id": "8145",
    "schedule_week": 1,
    "updated_at": "2026-10-22T23:15:00Z"
  }
  ```
- `400 Bad Request`: Payload validation failure (missing fields, invalid action, non-numeric week).
- `401 Unauthorized`: Missing or incorrect `x-lockin-passcode`.
- `409 Conflict`: GitHub commit conflict after retry limit exceeded.
- `500 Internal Server Error`: Upstream GitHub API error or network failure.

### 5.4 Vercel environment variables & security
- `LOCKIN_PASSCODE`: Secret string chosen by the user. Kept strictly server-side.
- `GITHUB_TOKEN`: Fine-grained GitHub Personal Access Token.
  - **Repository permissions:** `Contents: Read and write` strictly scoped to repository `mkodithuwakku/LockInModel`.
  - **Account permissions:** None.
  - **Expiration:** Configured for 1 year with rotation reminder.
- `GITHUB_REPO`: `mkodithuwakku/LockInModel`
- `GITHUB_BRANCH`: `main`

### 5.5 GitHub commit implementation details
The function uses the GitHub REST API (`GET /repos/{owner}/{repo}/contents/{path}` and `PUT /repos/{owner}/{repo}/contents/{path}`):
1. Fetches current `state/locks.json` from `main` along with its git blob `sha`. If 404, initializes an empty schema.
2. Applies the requested lock or unlock operation, updating `updated_at`.
3. Purges any leagues whose `schedule_week` is older than the current payload's week.
4. Serializes formatted JSON and commits to `main` with `PUT`:
   - Commit message: `Update locks: [action] [player_name] (Week [week])`
   - Author: `LockIn Phone <lockin-phone@users.noreply.github.com>`
5. **Conflict resolution:** If GitHub returns `409 Conflict` (another write occurred between GET and PUT), back off 250ms and retry up to 3 times.

---

## 6. Daily pipeline and Mac publisher integration

### 6.1 Fast-forward pull before daily analysis
In `publication.py`, `run()` must incorporate remote lock updates before refreshing analysis:

```python
# In publication.py before refresh_report()
def sync_remote_locks(config):
    """Pull remote lock changes committed from the phone before running analysis."""
    try:
        git("fetch", config["remote"], "main", cwd=ROOT)
        git("merge", "--ff-only", f"{config['remote']}/main", cwd=ROOT)
    except Exception as e:
        # A failed fetch or non-fast-forward merge must not abort publication;
        # log warning and proceed with local state.
        logger.warning(f"Could not fast-forward main for remote locks: {e}")
```

### 6.2 Storage helper: `storage.py`
Add `load_locks()` and `save_locks()` to `storage.py`:
- `load_locks()`: Reads `state/locks.json` safely. Returns `{}` if file does not exist or is malformed.
- `save_locks(locks)`: Writes atomically via temporary file and `os.replace`.

### 6.3 Static export allowlist: `pages.py`
`pages.py` must export lock state to the public static site:
- In `public_team()`: Attach `locks` map for that team/league to the public JSON payload.
- In `public_slot()`: Include `pinned: true`, `locked: true`, and `locked_fp: 54.5` on the slot object if pinned.

---

## 7. Lineup optimizer (`lineup.py`) pinning semantics

### 7.1 Algorithm modification
Do NOT alter the core `optimal_assignment()` bipartite Hungarian implementation. Instead, **pre-filter pinned slots and players before Hungarian assignment**:

1. **Partition active slots:**
   - For each active slot in `team["roster_positions"]`:
     - Check if the slot index has a matching lock record in `team_locks`.
     - If pinned:
       - Match the pinned player in `rows`.
       - Designate the slot as **pinned**: assign the player directly to `slot[i]`.
       - Mark `pinned_slots.add(i)` and `pinned_players.add(player_identity)`.
     - If not pinned:
       - Add slot to `unpinned_slots`.
2. **Filter candidates:**
   - Candidate pool for Hungarian assignment includes only eligible roster players `p NOT IN pinned_players`.
3. **Solve remaining:**
   - Run `optimal_assignment(unpinned_slots, remaining_candidates)`.
4. **Merge and reconstruct:**
   - Recombine pinned slots and Hungarian assignments into the complete `slots` array in original starter order.
   - Pinned slots carry:
     ```python
     {
         "slot": slot_name,
         "slot_index": i,
         "player": pinned_player_name,
         "player_id": pinned_player_id,
         "projected_fp": locked_fp, # Displays banked score
         "is_pinned": True,
         "is_locked": True,
         "lineup_reason": "Pinned starter (locked in Sleeper)"
     }
     ```

### 7.2 Edge cases and resolution rules

| Edge Case | Expected Behavior |
| :--- | :--- |
| **Locked player has a game today** | Stays in pinned slot. Score is already locked; projected FP does not override banked score. Today's game carries `status: "locked"`. |
| **Locked player has NO game today** | Stays in pinned slot. Prevents other scheduled players from occupying that slot. Slot projected FP reflects the locked score, not 0. |
| **All active slots are locked** | Zero unpinned slots remain. `optimal_assignment` is skipped entirely. Status is `"locked"` / `"ready"`. |
| **Locked player is on IR/Taxi** | Illegal Sleeper state. Produce a `DATA_ALERT` warning: *"Locked player is in reserve slot"*. Slot is treated as unpinned. |
| **Locked player has a negative locked score** | Stays in pinned slot. Unlike ordinary Hungarian optimization which drops negative players, locked players MUST start. |
| **Duplicate slots (e.g. 2x UTIL)** | Disambiguated by `slot_index` from the ordered `starters` list. |

---

## 8. Client-side presentation and immediate re-pinning

### 8.1 Why client-side re-pinning is mandatory
A manager locks a score at 10:30 PM after a West Coast game finishes. The Mac will not run daily publication until 7:00 AM.
If re-pinning were server-only:
- The phone UI would display the locked player being moved or benched all night.
- The manager could not trust the dashboard during evening planning.

**Decision:** The client (`web/insights.js` and `web/app.js`) implements the identical pre-filtering pinning logic in JavaScript. When the user toggles a lock:
1. Local state updates immediately (optimistic UI).
2. `rosterSheet()` in `web/insights.js` pre-filters pinned slots and re-runs the Hungarian assignment in browser memory.
3. The background POST is dispatched to Vercel.
4. If the POST fails, the toggle reverts with a dismissible error toast.

### 8.2 UI and visual styling
In strict compliance with [AGENTS.md](../../AGENTS.md):
- **Placement:** A compact lock icon button sits directly in the roster row, beside the existing player name and status indicators.
- **Palette:**
  - Unlocked state: Muted charcoal/steel outline (`#3a3d45`), opacity 0.5 on hover.
  - Locked state: Subtle gold padlock icon (`#d4af37`), solid fill, with a muted plum badge `LOCKED`.
- **Roster-first hierarchy:** Toggling never adds banners or pushes the roster sheet down.
- **Passcode input:** When tapped for the first time, a minimal dialog prompts for the Passcode. The passcode is stored in browser `localStorage` (`lockin_passcode`) and reused on future toggles.

---

## 9. Auto-detection layer (Phase 2)

*Status: Reserved for Phase 2. Not required for MVP.*

During sync/refresh, `sleeper.py` can query `/league/{id}/matchups/{week}`:
1. Examine `matchup["players_points"]` for each rostered starter.
2. Compare the recorded score against the league-scored box scores of that player's games in the current fantasy week.
3. **Definitive lock rule:**
   - If player had 2 games (e.g. Tuesday: 48 FP, Thursday: 22 FP), and `players_points == 48.0`:
     - The player is **definitively locked** on Tuesday's game.
     - Auto-generate a lock entry in `state/locks.json`.
   - If `players_points == 22.0` (matching the latest game):
     - Cannot distinguish whether it is locked or simply counting the latest score. Do not auto-lock.

---

## 10. Security and threat model

1. **Token protection:**
   - The GitHub Personal Access Token is stored strictly as a Vercel environment variable (`process.env.GITHUB_TOKEN`).
   - The token is NEVER embedded into static HTML, JavaScript bundles, git commits, or `report.json`.
2. **Endpoint authorization:**
   - The Vercel function rejects any request lacking `x-lockin-passcode: <valid_passcode>`.
   - Timing-safe comparison prevents timing attacks on the passcode.
3. **Threat assessment:**
   - *Threat:* Unauthorized user finds the Vercel URL and attempts to toggle locks.
   - *Impact:* Minor nuisance (marking a fantasy player locked in a personal dashboard). No access to private financial, personal, or hosting infrastructure.
   - *Mitigation:* Secret passcode + Vercel IP rate limiting (10 requests per minute per IP).
4. **Token scope confinement:**
   - Fine-grained token has access *only* to `mkodithuwakku/LockInModel` and *only* `Contents: Read and write`. Cannot delete repository, modify GitHub Actions workflows, or alter branch protection.

---

## 11. Failure modes and mitigations

| Failure Scenario | Impact | Mitigation / Recovery |
| :--- | :--- | :--- |
| **Vercel endpoint is down / offline** | Phone toggle fails to persist to GitHub | Client shows toast: *"Could not save lock to cloud. Stored locally on device."* Reverts optimistic UI if local fallback disabled. |
| **GitHub API returns 409 Conflict** | Concurrent edits to `state/locks.json` | Vercel function retries 3 times with exponential backoff and re-fetches latest SHA. |
| **Mac is asleep during night locks** | No impact on phone | Vercel commits to GitHub independent of Mac. Mac catches up on morning wake via `git pull`. |
| **Player was locked, then traded/dropped** | Pinned player no longer in roster `starters` | Pipeline emits warning notice in Data Alerts: *"Locked player [Name] is no longer on team roster."* Drops lock gracefully. |
| **Week rollover happens mid-week** | Schedule week increments in Sleeper | Locks with mismatched `schedule_week` auto-expire; engine ignores them. |
| **Passcode is compromised** | Attendant can edit locks | User changes `LOCKIN_PASSCODE` in Vercel dashboard and re-enters on phone. |

---

## 12. Testing and verification plan

### 12.1 Python unit tests (`.venv/bin/python -m pytest`)
Create `tests/test_lineup_pinning.py` covering:
1. `test_pinned_player_occupies_exact_slot`: Pinned player remains in slot even when Hungarian optimizer would prefer another player.
2. `test_pinned_player_with_no_game_blocks_slot`: Locked player on off-day prevents bench players from starting in that slot.
3. `test_unpinned_slots_optimize_normally`: Remaining slots solve correctly.
4. `test_all_slots_pinned`: Full roster locked produces ready status without running Hungarian solver.
5. `test_expired_week_locks_ignored`: Locks from Week 1 do not apply to Week 2.
6. `test_malformed_locks_file_fails_closed`: Corrupt JSON defaults to empty locks with logged warning.

### 12.2 Node frontend tests (`node --test tests/*.test.cjs`)
Create `tests/lineup_pinning.test.cjs` covering:
1. Client-side re-pinning in `web/insights.js` matches Python output.
2. Roster sheet ordering puts pinned players first with `LOCKED` label.
3. Toggling lock state updates slot projected total to banked score.

### 12.3 Serverless function testing (Vercel)
Test `api/lock.ts` locally using `vitest` or mock requests:
- Mock GitHub REST API GET and PUT endpoints.
- Test valid lock, valid unlock, invalid passcode (401), conflict retry (409 -> 200).

---

## 13. Open decisions and recommendations

| Decision | Options | Recommended Choice | Rationale |
| :--- | :--- | :--- | :--- |
| **Serverless host** | Cloudflare Workers vs AWS Lambda vs Vercel | **Vercel** | User preference; zero-config TypeScript functions in `api/`; excellent GitHub integration. |
| **Repository target branch** | Dedicated `locks` branch vs `main` | **`main`** | User preference; keeps repo history unified. Small JSON commits to `state/locks.json` avoid branch merge ceremony. |
| **Post-refresh re-pinning** | Server-only vs Client-side JS | **Both** | Client re-pins instantly for the phone user at night; Mac validates and freezes it into the static export at 7 AM. |
| **Passcode UX** | HTTP Basic Auth vs Custom Header + LocalStorage | **Header + LocalStorage** | Avoids ugly browser auth dialogs; matches modern mobile web apps; entered once and stored. |
| **Identifier key** | Sleeper ID vs Canonical Name | **Sleeper ID with name fallback** | Immune to name spelling discrepancies; canonical name preserves human readability in git diffs. |

---

## 14. Documentation updates required by AGENTS.md

Upon implementation, the following documentation must be updated in the same change:
1. `README.md`:
   - Add locked-player pinning to *Key features*.
   - Update architecture diagram to show the Vercel write bridge.
   - Note limitations: lock flags are manager-reported, not verified via Sleeper push.
2. `docs/ARCHITECTURE.md`:
   - Document `state/locks.json` and `api/lock.ts`.
   - Update request flow and security boundary.
3. `docs/CONFIGURATION.md`:
   - Add `LOCKIN_PASSCODE` configuration instructions.
4. `docs/OPERATIONS.md`:
   - Add Vercel deployment and secret setup instructions.
5. `docs/KNOWN_ISSUES.md`:
   - Note that auto-detection is planned for Phase 2.
