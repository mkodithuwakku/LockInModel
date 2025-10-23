LockInModel – Debugging & Run Cheatsheet

This project pulls NBA logs nightly and recommends LOCK vs WAIT for your fantasy lineup using a weighted baseline (recent games count more) plus early-season guards (career-aware variance floor and rookie fallback).

1) Setup

Create and activate a virtual environment (macOS/Linux):

python3 -m venv venv
source venv/bin/activate


Install dependencies:

pip install -r requirements.txt


(If you don’t have a requirements.txt yet, install explicitly):

pip install nba_api pandas numpy scikit-learn pyyaml python-dotenv

2) Environment variables

Set these in your shell (or use a .env that your app loads):

# Email credentials (Gmail app password required)
export EMAIL_USER="you@gmail.com"
export EMAIL_APP_PASSWORD="your-16-char-app-password"

# Logger level (DEBUG shows math details; INFO is quieter)
export LOG_LEVEL=DEBUG


Optional debug toggles:

# Show per-stat rarity z-scores in logs (BLK/STL etc.)
export TRACE_RARITY=1
# Dump the baseline input window for each player to CSV
export DEBUG_DUMP_DIR="debug"

3) Running the tool

From the project root:

python main.py


Typical “debug mode” run:

export LOG_LEVEL=DEBUG
export TRACE_RARITY=1
export DEBUG_DUMP_DIR=debug
python main.py


Deactivate the venv when you’re done:

deactivate

4) What you’ll see in DEBUG logs

For each player:

FP describe: count/mean/std/min/25%/50%/75%/max over all fetched logs

Week range and which dates had games this week

Last game row: one-line JSON with stats and FP used for decision

Remaining games estimate this week

Baseline window: size, date span used to compute the baseline

Baseline internals:

mu_post: mean after shrinkage toward career prior (if available)

sd_post: std after early-season guard (career-scaled; rookies use 17.5)

career_prior: career FP used as prior (if available)

guard: SD floor applied (career-based or 17.5 rookie guard)

decay: exponential recency factor used to weight recent games

Probability math (Normal model):

z, Φ(z), P(all ≤ current), P(max > current)

Rarity (if TRACE_RARITY=1): per-stat z-scores that contributed to rarity

Final decision: LOCK/WAIT with p_lock, p_wait, rarity

If DEBUG_DUMP_DIR is set, a CSV of the baseline window per player is saved at:

debug/<Player_Name>_baseline_window.csv

5) Config knobs (config.yaml)

Under the decision section:

decision:
  # Recency weighting (ALWAYS ON in code; this is the strength)
  decay: 0.92

  # Career/rookie early-season guards
  prior_weight_games: 12     # pseudo-games that shrink recent mean toward career FP
  sd_floor_min: 4.0          # absolute minimum SD floor
  career_guard_scale: 0.6    # SD floor = max(sd_floor_min, career_guard_scale * career_FP)
  rookie_guard_fp: 17.5      # SD floor when career FP is 0 or missing (rookie)

  # Rarity & biases
  rare_stats: ["BLK","STL"]
  rare_z_threshold: 1.75
  lock_bias_if_rare: 0.15
  min_remaining_games_bias: 0.05
  conservative_mode: false

  # Optional per-player overrides (by display name)
  player_overrides:
    "Shai Gilgeous-Alexander":
      decay: 0.94
      prior_weight_games: 16
      career_guard_scale: 0.7


Notes

The baseline always weights recent games exponentially.

The mean is shrunk toward the player’s career FP when samples are small.

The SD guard is derived from career FP (or 17.5 for rookies).

6) Troubleshooting

SMTPAuthenticationError 535

Use a Gmail App Password (Google Account → Security → 2-Step Verification → App Passwords).

Ensure EMAIL_USER and EMAIL_APP_PASSWORD match the same Google account.

nba_api JSONDecodeError / TLS warnings

Often transient NBA Stats API responses or local TLS quirks.

You already pinned urllib3<2 for macOS LibreSSL; retry usually resolves.

If persistent, try a different network or wait a few minutes.

“No games yet this week”

Expected early in the week/season or when a player hasn’t played in the current Monday–Sunday window.

Nothing prints at DEBUG level

Ensure you exported LOG_LEVEL=DEBUG in the same shell before running.

7) Typical workflows

Nightly run (cron/launchd):

source /path/to/project/venv/bin/activate
export LOG_LEVEL=INFO
python /path/to/project/main.py


Deep dive on a specific issue:

source venv/bin/activate
export LOG_LEVEL=DEBUG
export TRACE_RARITY=1
export DEBUG_DUMP_DIR=debug
python main.py
# Inspect debug/*.csv and terminal logs

8) Support

If a player’s decision looks off, copy the full DEBUG block for that player (from
“== Evaluating … ==” through the “Decision” line) and share it — those numbers are enough to pinpoint whether the baseline, guard, rarity, or probability needs tuning.