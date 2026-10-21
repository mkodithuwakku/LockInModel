# Configuration reference

`storage.load_cfg()` loads `config.local.yaml`, falling back to the sanitized `config.yaml`. Both the dashboard and CLI use this function. Local changes are atomically persisted; personal settings stay outside version control.

## Teams

Each team contains a stable `id`, `name`, complete `players` list, and `starters` subset. The UI can add, remove, or toggle local players. The older `team_roster` field is only a migration fallback; legacy starter JSON is no longer read.

Imported Sleeper teams additionally contain `source`, `league_id`, `league_name`, `season`, `league_status`, `synced_at`, `weights`, `unsupported_scoring`, `ignored_scoring`, `owned_players`, and player-position metadata. A sync refreshes membership and scoring from Sleeper. Imported rosters cannot be manually edited in this UI, avoiding two competing sources of truth.

When Sleeper teams are present, original local rosters move to `test_teams` practice templates; `teams` contains the synced league entries. Older seasons carry `archived: true`. Runtime practice edits stay in `state/test-week.json`, separate from this configuration.

The global `sleeper` object saves a username and season start year. The daily command checks the upcoming/current basketball season and falls back to the saved season if the newer one has no leagues yet.

## Scoring

Supported columns are PTS, REB, AST, STL, BLK, TOV, FG3M, FGM, FGA, FTM, FTA, OREB, DREB, PF, DD, TD, and milestone fields such as PTS40, PTS50, AST15, and REB20. Weights must be finite numbers. The default sample configuration uses:

```text
0.5·PTS + REB + AST + 2·STL + 2·BLK − TOV + 0.5·FG3M
+ DD + 2·TD + 2·PTS40 + 2·PTS50
```

Bonuses stack: a triple-double receives DD and TD; 50 points receives both point-threshold bonuses. Any positive integer threshold for PTS, REB, AST, STL, or BLK can be appended to the stat name, such as `AST15: 3`, `REB20: 5`, or `STL5: 2`. Each adds its configured weight once when the observed stat reaches that threshold. Zero disables it. The sample defaults include AST15 and REB20 at zero so existing sample scoring is unchanged.

Sleeper rule names are translated explicitly, including `to → TOV` and `tpm → FG3M`. Milestones matching `bonus_(pt|reb|ast|stl|blk)_<threshold>p` are imported automatically: `bonus_ast_15p → AST15` and `bonus_reb_20p → REB20`. The same migration applies when loading older saved configurations. Global and per-team weights are validated; each league retains its own formula.

For example, adding `AST15: 3` and `REB20: 5` to a local team's existing `weights` adds 3 FP for at least 15 assists and 5 FP for at least 20 rebounds, independently of ordinary assist/rebound points. A game reaching both gains 8 bonus FP. These are illustrative weights, not global defaults. Imported league weights are refreshed from Sleeper on sync; use that league's settings as the authority. Changing weights rescales stored observations at scoring time and does not require a new database or new threshold-specific Python code.

Technical and flagrant foul penalties (`tf`, `ff`) are omitted and retained in `ignored_scoring` metadata. Personal fouls (`PF`) use actual values when available and are omitted otherwise. Offensive/defensive rebound weights use actual splits when available; otherwise the model uses total rebounds with coefficient `REB weight + (OREB weight + DREB weight) / 2`, treating an absent split weight as zero. Equal split weights are exact; unequal weights are an approximation. These approved adjustments are shown as information and do not block recommendations. Other unknown nonzero rules still withhold actionable recommendations.

## Decision controls

| Key | Default | Meaning |
| --- | --- | --- |
| `lookback_games` | 10 | Recent baseline limit and current-season game count needed to stop filling lock/projection windows with prior-season games |
| `recent_days` | 14 | Baseline time window before limiting rows |
| `decay` | 0.92 | Exponential recency weighting |
| `prior_weight_games` | 12 | Mean-shrinkage pseudo-game count |
| `sd_floor_min` | 4.0 | Minimum SD, including three-plus-game histories |
| `career_guard_scale` | 0.6 | Prior-derived SD guard for tiny samples |
| `rookie_guard_fp` | 17.5 | Tiny-sample guard without a prior |
| `rare_stats` | BLK, STL | Base rare-event columns |
| `rare_z_threshold` | 1.75 | Minimum qualifying rarity z-score |
| `lock_bias_if_rare` | 0.15 | Rarity multiplier added to lock score |
| `min_remaining_games_bias` | 0.05 | Wait preference when at least two games remain |
| `conservative_mode` | false | Adds 0.05 to lock score |

Per-player `player_overrides` support `decay`, `prior_weight_games`, and `career_guard_scale` by exact display name. Rarity needs at least three prior games with positive variance. Missing or constant variance no longer creates huge artificial rarity signals.

Pickup thresholds are currently explicit constants in `pickups.py`: five recent games, at least eight earlier observations, at least 4 FP improvement and 0.5 baseline SD, 60% consistency, and at least 18 recent minutes. These are screening heuristics, not fitted thresholds.

## Notifications and environment

`notify.to_email` and `notify.from_email` are local addresses. Each defaults to EMAIL_USER if blank during delivery. SMTP uses Gmail over SSL on port 465, with a 20-second timeout.

| Environment variable | Purpose |
| --- | --- |
| `EMAIL_USER` | SMTP username |
| `EMAIL_APP_PASSWORD` | SMTP app password; use a replacement for any previously exposed password |
| `LOG_LEVEL` | INFO by default; set before launching for consistent import-time logging |
| `LOG_FILE` | Optional logging destination |
| `TRACE_RARITY` | Set to 1 before launching to inspect usable stat rarity inputs |

`main.py` and `app.py` load `.env`. Copy `.env.example` for placeholders; never commit credentials. `DEBUG_DUMP_DIR`, the old `gui.title`, and SMS settings are no longer active application controls.

The application date uses America/Edmonton. Test Week controls its own morning/night clock; the CLI `--date` option selects an end-of-day historical cutoff. Neither changes the computer's clock.

## Imported player display metadata

Sleeper imports preserve the ordered starter slots from `roster_positions` and `starters`, including empty positions in the source array. Bench/reserve/taxi players receive BN/IR/TAXI labels. `player_meta` stores NBA team, fantasy positions, injury status, lineup order, and source player ID. Display metadata remains available when performance data fails. It is refreshed by import; avoid manually editing synced team records. Local practice teams without slot metadata show START/BN instead of guessing a league position.

## Local publication

The optional `publication` mapping defaults to `remote: origin`, `branch: gh-pages`, `hour: 12`, `minute: 17`, and `timezone: America/Edmonton`. An optional HTTPS `url` supports a custom Pages domain; otherwise it is derived from the GitHub origin. Source branches `main`/`master` cannot be publication targets. GitHub credentials come from the existing OS Git credential helper, never from YAML or a generated website file.

The macOS agent checks at minutes 02, 17, 32, and 47 and after login/wake. The ledger permits one successful publication per scheduled date. For other configured minutes, the next check after the configured time performs the run (at most 15 minutes later while awake). Failures retry after 15, 30, 60, 120, 240, then 360 minutes; subsequent failures remain capped at six hours. See [Hosting](HOSTING.md).

## Daily lineup slots

Sleeper sync saves `roster_positions` from the league API, including empty slots and duplicates, alongside each player's `positions`, `roster_slot`, and injury label. Each league can therefore have its own active configuration. Sync older imports once to populate this field; daily publication already syncs automatically.

A local/practice team can set, for example:

```yaml
roster_positions: [PG, SG, F, C, UTIL, UTIL, BN, IR]
```

PG/SG/SF/PF/C, G/F, and UTIL are supported active slots. BN/IR/TAXI are excluded. The config validator preserves order and duplicates and normalizes names to uppercase. Unrecognized active slot names make the recommendation unavailable rather than silently changing a league's rules. Local teams without this field use one UTIL slot per starter. Imported teams without it request a resync.

Daily projections reuse `decision.lookback_games`, `recent_days`, `decay`, and `prior_weight_games`, together with that league's scoring weights. Both projections and weekly locks fill a sparse current-season window with actual prior-season games until `lookback_games` current-season appearances exist (default 10), including midseason returns. During this blend, `recent_days` does not discard the historical rows and `prior_weight_games` is not applied a second time. Missing historical games are not fabricated. No player-specific or league-specific lineup algorithm is needed. Read [daily lineup assumptions](MODEL.md#11-daily-lineup-projections-and-assignment) before treating a suggested arrangement as a legal Sleeper change.

## Forecast fallback and scoring display

Current-season Sleeper / RotoWire forecasts are retrieved during live refresh for imported players, with a six-hour cache. No credentials, new database, extra scheduler, or per-player configuration are needed. When current game history is absent, these forecasts precede the historical fallback and are rescored with each league's weights. See [Projections](PROJECTIONS.md) for expected milestone bonuses. Approved scoring adjustments appear inside player details under Scoring method rather than Data alerts.
