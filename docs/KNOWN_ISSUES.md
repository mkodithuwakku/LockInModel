# Known issues and remaining work

## Corrected in this implementation

- Full-roster projected box scores are visible independently of start eligibility. Validated current-season Sleeper forecasts cover missing current history, including rookies. Approved scoring choices no longer inflate Data alerts.

- Daily lineups preserve full league slots (including empties), maximize eligible projected FP with exact assignment, and remain as dated snapshots until the next refresh. Predictions are baselines, not demonstrated accuracy.

- Bonuses are recomputed from observations, including configurable points/rebounds/assists/steals/blocks thresholds. Boundary and stacking cases are tested.
- Unavailable fouls and rebound splits use documented fallbacks and informational notes; they no longer block recommendations. Unknown nonzero rules still do.
- SQLite retains shared live game history with transactional upserts, daily overlap downloads, weekly reconciliation, and failed-refresh retention.
- Daily website generation moved from GitHub Actions to a Mac LaunchAgent. Catch-up timing, retries, export isolation, and pending deployment confirmation are tested; GitHub serves the static result.
- Reports retain their original timestamp across midnight and expire after 26 hours or at the next fantasy week, with stale actions suppressed.
- Empty/failed schedules no longer become zero remaining games or confident LOCKs. The live calendar is fetched once per season-cache window and shared across players.
- Drafted preseason leagues no longer request nonexistent regular-season stats; opening-week opponents and UPCOMING status remain visible.
- NBA team labels and ordered lineup slots survive provider failures; shortened Sleeper names prefer active NBA identities.
- The UI and reports share canonical YAML; the disconnected Tkinter selection path was replaced.
- `.env`, virtual environments, editor files, and runtime state were removed from tracking and ignored.
- HTTP calls are cached, paced, time-bounded, and protected by persistent failure cooldowns.
- Historical capture and offline replay exist, with explicit time and prior policies.
- Repeated email attempts are suppressed, including uncertain SMTP delivery outcomes.
- Constant/tiny rarity variance no longer creates artificial extreme rarity signals.
- Season review dashboard aggregates full current-roster season production, box-score sums, weekly FP per appearance, and sample-gated key player cards.
- Season Badge race tracks 44 badge categories across the season with roster and NBA-wide views, total awards, chaos leader, milestones, and badge variety.
- Expanded player card includes a season badge section with repeat counts, earned-badge breakdown, and outside-tap backdrop dismissal.
- Player performance colours share a consistent personal recent-baseline comparison across player cards, weekly schedule tiles, and roster rows.
- Daily contextual and milestone badges cover 44 indicators with a compact badge guide modal and SQLite pregame forecast comparison archive.
- Observed-history bootstrap blends prior-season games into sparse current projections and weekly lock baselines without duplicate shrinkage.
- Validated Sleeper / Sportradar game-level box-score fallback recovers finals when NBA Stats is unavailable or misses recent games.
- Locked-player pinning freezes Sleeper lock-in starters in their assigned slot with banked scores, pre-filtering Hungarian optimizer candidates.
- Vercel serverless bridge (`api/lock.ts`) commits lock toggles to `state/locks.json` on `main`; Mac publication pulls remote locks before analysis.
- Off-day lineup filling populates open slots with healthy idle players as zero-projection placeholders so the roster sheet is never vacant.
- Games to watch view aggregates and ranks today's NBA matchups across all imported fantasy leagues.
- Dedicated Badge race navigation view provides an NBA-wide default and accounts for mutually exclusive age badges in variety caps.
- Schedule-aware add/drop swap suggestions evaluate short-term schedules against a next-week horizon, advising hold when net gain is non-positive.
- Stock Expert badge enforces at least one steal and one block requirement.
- Normalized relational SQLite schema (v2) with `dim_teams`, `dim_players`, `fact_game_logs`, and `dim_refreshes`, eliminating duplicate unindexed JSON payloads.
- Opponent-aware Ridge component projections (`features.py`, `model_ml.py`) score every unplayed weekly game tile with matchup-specific `proj_fp` and overlay same-day lineup profiles.
- Opponent-aware lock/wait decision probabilities evaluate per-game means across remaining matchups (`future_mus`), tagged with `decision_model: "opponent_ridge"`.
- Offline evaluation harness (`evaluator.py`) provides per-game error metrics, walk-forward backtests, weekly lock regret vs Oracle, and hyperparameter grid tuning.
- Biweekly model-check LaunchAgent (`model_check.py`) automatically evaluates live-season drift and fixture tuning sweeps without manual intervention.

## Credential and Git history handling

The repository is public, and the configured email app password matched the one committed in its original history. The local guard blocks that password. Revoke and replace it in Google; Git cleanup cannot revoke a credential.

Removing secrets from the current tree is separate from purging historical commits. `main` now follows the cleaned project history from `modernize-dashboard`, including the dashboard redesign, current README, and portrait fallback fix. The former `main` was backed up privately on the local computer before promotion. Do not merge the original history back into the cleaned branches. Other legacy refs (including `opponentWeighting`), old clones, and provider caches can still retain historical contents; promoting `main` does not establish complete repository-wide erasure or credential revocation.

Local credentials, imports, cache files, and `.venv` remain on the computer; removing them from tracking does not delete those local files.

## Functional limitations

| Area | Limitation |
| --- | --- |
| League scoring | Unavailable fouls are omitted; unavailable rebound splits are approximated using total rebounds. Generic milestone bonuses are computed. Unknown nonzero rules still block recommendations |
| Sleeper lock state | The Sleeper API exposes no lock field, so flags are user-supplied and unverified. Toggling in LockIn never submits anything to Sleeper. A wrong or stale flag can pin a player who is not actually locked until the manager removes the flag or the week rolls over; the matchup-score auto-detection layer remains planned |
| Lock flag propagation | Phone toggles write `state/locks.json` through an optional serverless function; without a deployed endpoint the flag is device-local only. GitHub commit propagation to Pages is near-instant for the browser's optimistic re-pin, but the authoritative lineup reflects it only at the next Mac publication. If the Mac cannot fast-forward `main`, it publishes its local lock state and logs a warning |
| Lock endpoint auth | When `LOCKIN_PASSCODE` is unset the write endpoint is unauthenticated by design (phone prompts only on a 401). Schema validation and an Origin-header check block malformed and casual requests, but anyone who finds the URL can flip lock flags and leave commits on `main`. The GitHub token scope is Contents on this repo only; `state/locks.json` is the sole writable path |
| Live availability | NBA Stats may reject or time out on local requests. Saved history is retained but cannot supply newly missed games. Rosters and independently verified Sleeper schedules remain visible; no performance recommendations are invented during an outage |
| Schedule feed | Public Sleeper schedule schema is not part of the core documented v1 league API. Dates/opponents are available; tip-off times are not. Changes/postponements wait for cache refresh |
| Offseason | Completed leagues produce no active recommendations; new-season rosters must exist before meaningful live analysis |
| Historical schedules | Finalized schedule and last observed team assignment, not timestamped historical schedule/transaction snapshots |
| Practice fidelity | Whole-night clock and sample rosters/rules; no exact game deadlines, full Sleeper transaction rules, or opponent matchup simulation |
| Historical ownership | Current import or sample roster; availability claims are not historical |
| Injury/role context | Daily lineups exclude confirmed-out/reserve players from the import snapshot; questionable players have no probability adjustment. Historical injuries and future role/minute changes are not modeled |
| Pickup projection | Hand-tuned conservative estimate, not a fitted/calibrated forecast |
| Position fit | Exact daily positional assignment is implemented; weekly lock optimization, Game Pick selections, transaction legality, and waiver-budget strategy are not |
| Local configuration | Atomic writes, but no cross-process configuration transaction lock; one editor process is intended |
| Deployment | GitHub Pages serves a public static snapshot without a database. Updates require the Mac logged in, awake, online, and authenticated to GitHub; source pushes alone do not deploy. Catch-up cannot restore missed decision deadlines. Local Flask has no public login; Test Week and editing stay local |
| Live storage | Upserts replace corrected observations; no historical versions are retained, and records absent from a later response are not deleted. Backups remain a local operational responsibility |
| Verification | Catch-up logic is tested with simulated times; a physical Mac sleep/wake cycle is not verified. Existing generic screenshots predate the new scoring notices |
| Runtime | Existing Python 3.9/LibreSSL environment retained; modern runtime and dependency upgrade remains desirable |
| License | No project license chosen |

## Priorities after this release

1. Confirm the exposed credential was revoked/replaced and review remaining legacy refs and cached copies after the cleaned-history promotion to `main`.
2. Evaluate the impact of the approved foul omission and rebound approximations; unknown scoring formats still require explicit support.
3. Verify live inputs when the next leagues and games become active.
4. Evaluate the lock and pickup policies across multiple held-out weeks.
5. Add richer injury/role context and precise historical roster/schedule snapshots where useful.

There are no established accuracy, profit, win-rate, or production-scale claims.

## Forecast limitations

The current Sleeper forecast feed is outside the documented v1 league API and may change schema. Invalid records cannot authorize projections. Projected box-score averages do not determine milestone frequencies; missing frequencies use an explicitly labeled Poisson approximation (and independence for multi-category bonuses). Forecasts are conditional on playing, not injury-adjusted appearance probabilities. Historical charts use actual observations only, so a new NBA player can have a forecast without a chart.
