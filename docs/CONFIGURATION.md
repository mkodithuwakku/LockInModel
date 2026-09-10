# Configuration reference

`storage.load_cfg()` loads `config.local.yaml`, falling back to the sanitized `config.yaml`. Both the dashboard and CLI use this function. Local changes are atomically persisted; personal settings stay outside version control.

## Teams

Each team contains a stable `id`, `name`, complete `players` list, and `starters` subset. The UI can add, remove, or toggle local players. The older `team_roster` field is only a migration fallback; legacy starter JSON is no longer read.

Imported Sleeper teams additionally contain `source`, `league_id`, `league_name`, `season`, `league_status`, `synced_at`, `weights`, `unsupported_scoring`, `owned_players`, and player-position metadata. A sync refreshes membership from Sleeper. Imported rosters cannot be manually edited in this UI, avoiding two competing sources of truth.

When Sleeper teams are present, original local rosters move to `test_teams` practice templates; `teams` contains the synced league entries. Older seasons carry `archived: true`. Runtime practice edits stay in `state/test-week.json`, separate from this configuration.

The global `sleeper` object saves a username and season start year. The daily command checks the upcoming/current basketball season and falls back to the saved season if the newer one has no leagues yet.

## Scoring

Supported columns are PTS, REB, AST, STL, BLK, TOV, FG3M, FGM, FGA, FTM, FTA, DD, TD, PTS40, and PTS50. Weights must be finite numbers. The default sample configuration uses:

```text
0.5·PTS + REB + AST + 2·STL + 2·BLK − TOV + 0.5·FG3M
+ DD + 2·TD + 2·PTS40 + 2·PTS50
```

Bonuses stack: a triple-double receives DD and TD; 50 points receives both point-threshold bonuses. These indicators are now retained through the full pipeline.

Sleeper rule names are translated explicitly, such as `to → TOV`, `tpm → FG3M`, and `bonus_pt_40p → PTS40`. Nonzero unsupported settings are recorded rather than ignored. The UI withholds lock recommendations and labels partial FP for those leagues. Technical/flagrant fouls are currently unsupported.

## Decision controls

| Key | Default | Meaning |
| --- | --- | --- |
| `lookback_games` | 10 | Maximum rows in the recent lock baseline |
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

The initial daily timezone is America/Edmonton. The dashboard date picker is an explicit historical end-of-day cutoff; it does not change the computer's clock.
