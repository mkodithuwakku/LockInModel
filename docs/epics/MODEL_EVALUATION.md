# Epic proposal: projection, lock-policy, and backend evaluation

**Status:** implemented and merged to `main` — offline evaluation engine in `evaluator.py`, walk-forward game backtests, sequential weekly-lock regret vs Oracle, hyperparameter grid search (`--mode tune`), slot-constrained team-weekly lock evaluation (`--mode team-weekly`, added by the [roster-aware lock epic](ROSTER_AWARE_LOCK_DECISIONS.md)), and biweekly macOS LaunchAgent `model_check.py` (`com.lockin.modelcheck`).

**Prepared:** October 21, 2026. Updated October 23, 2026.

**Reviewed baseline:** source commit `61c1c92` / `c5a33ac`.

**Delivery summary:** Evaluator implemented offline against `fact_game_logs` and fixture tables; benchmarks verified 26,066 paired game samples and 9,918 player-weeks. Automated model checks log to `state/model_check.json` and `state/model_check_history.jsonl`. See implementation runbook `docs/runbooks/EVALUATION_HARNESS.md`.

## 1. Purpose and delivery order

Answer two distinct questions with reproducible evidence:

1. **Game forecasts:** how close was the prediction saved before a game to the
   player's eventual stats and league-scored fantasy points?
2. **Weekly lock policy:** if someone followed the model at the available decision
   times, which performance would they retain, and how many points would that
   strategy gain or leave behind?

An accurate mean forecast does not establish a good stopping policy. Likewise,
selecting a good weekly performance does not prove that a displayed probability
is calibrated. Keep these scorecards separate.

Evaluation itself uses observed outcomes and statistical metrics; ML is optional
for learning error patterns, calibration, and challenger models. Start with the
measurement system, freeze today's model as B0, then test the opponent candidates
from the [opponent projection epic](OPPONENT_AWARE_PROJECTIONS.md). That epic's
OPP-04 evaluation work should use this shared backend rather than create another
competing evaluator. OPP-11 requires the separate weekly lock gate below.

On the future development branch, use a consistent SQLite backup or immutable
input exports for experiments, with a configured experiment path. Do not let
branch-specific migrations or historical runs mutate the live scheduler's DB.
This is a reproducibility artifact, not a second authoritative production DB.
Production will continue using one local SQLite database and static publication.

## 2. Existing capabilities and missing evidence

| Current capability | Useful foundation | Missing for rigorous evaluation |
| --- | --- | --- |
| `game_store.py` | Corrected observed player-game history | Revisions/known-at times needed to reconstruct what was available then |
| `forecast_store.py` | Real pregame FP snapshots by formula/date/player | Later pregame snapshots overwrite earlier ones; no model version, canonical game ID, feature snapshot or component distribution |
| `model.py` / `decide.py` | Current baseline, beat-current calculation and LOCK/WAIT logic | Immutable decision-time archive; raw probability is computed internally but only heuristic-adjusted `p_lock` is returned |
| `simulation.py` | Stateful practice and user-banked results | Batch sequential-policy evaluator across independent weeks and frozen rules |
| Captured fixtures | Repeatable full-season box scores and prior inputs | Historical injuries, transactions, real decision deadlines and as-known schedules |
| Daily publication | A dated, real-world cadence | Exact public visibility times tied to each recommendation revision and actual user lock selections |

Never relabel retrospective recomputation as a forecast actually published before
that game. The existing badge forecast archive can support a limited **legacy FP
comparison** where identity/date are unambiguous; label its missing provenance.
It is not sufficient to compare arbitrary past model versions or reconstruct
historical weekly user behavior. Existing badge tables remain compatible.

## 3. Proposed backend layout

All names below are proposed, not runnable modules or commands today.

| Future module | Responsibility |
| --- | --- |
| `evaluation/contracts.py` | Versioned forecasts, decisions, labels, cohorts and metric definitions |
| `evaluation/archive.py` | Append-only capture, idempotent joins and experiment manifests |
| `evaluation/datasets.py` | Frozen input exports, as-of joins, final-result reconciliation |
| `evaluation/splits.py` | Game-date / complete-week chronological partitions and embargoes |
| `evaluation/game_predictions.py` | Per-game FP/stat errors, intervals and slice scorecards |
| `evaluation/weekly_locks.py` | Sequential lock state machine, outcomes, regret and baseline policies |
| `evaluation/calibration.py` | Reliability diagnostics and optional fitted calibration challengers |
| `evaluation/lineups.py` | Slot-constrained realized lineup evaluation |
| `evaluation/operations.py` | Data coverage, freshness, latency, failure and resource benchmarks |
| `evaluation/reporting.py` | Versioned JSON, CSV and local HTML reports |
| `evaluation/run.py` | Explicit local orchestration; never called on a browser request |

Keep experiments/training separate from production scoring and model functions.
Call shared production logic through versioned adapters instead of copying its
formulas. Pin source revision, environment/dependencies and random seeds. Basic
metrics can use current numerical dependencies; add a separate optional evaluation
dependency set only when an implementation needs it. No paid platform is required.

After implementation, the existing refresh can append bounded snapshots and
reconcile newly final outcomes. Heavy historical replay/training remains an
explicit local run. Evaluation failure must not interrupt report publication.
Use indexed game/date/model keys and incremental completed-game/week jobs, not a
full-season retrain during every daily refresh. Cache identical scoring formulas.

## 4. Archive and label contracts

Use new versioned tables in the existing production DB when this is eventually
released. Keep the legacy forecast table until badge consumers have a tested
compatibility path. Store large immutable feature/input exports by content hash
outside the DB; they are experiment artifacts, not additional live sources.

- **Forecast revision:** ID, NBA game/player/season IDs, model/config/feature/scoring
  policy versions, formula hash, captured-at UTC, input-known-through timestamp,
  scheduled tip-off/status snapshot, horizon, forecast source and fallback reason,
  projected components/FP, conditional-on-playing flag, optional quantiles or
  distribution parameters, input artifact hash. Store a run/revision ID rather
  than overwriting every forecast for one player/date. Record all forecastable
  players, including unselected and ultimately inactive players.
- **Decision revision:** player, league formula and week boundaries, policy/model
  versions, decision timestamp, last eligible game and score, remaining schedule
  as then known, raw beat-current probability, adjusted lock score, LOCK/WAIT/
  abstain, input snapshot, legal expiry, simulated state and reasons. Retain later
  diagnostics separately after a policy has locked; they cannot replace its choice.
- **Delivery evidence:** generated and public-visible timestamps, report ID and
  forecast/decision revision IDs. A forecast generated before tip-off but published
  after its deadline is not an actionable website recommendation.
- **Outcome revision:** actual final game ID/stat line, source, observed-at time,
  status and correction revision. Store FP under the matching scoring policy;
  negative FP is valid. An absent row is not a zero-point game.
- **Weekly outcome:** frozen cohort/rules/cadence, candidate game IDs, selected game
  or terminal outcome, retained FP, best legally reachable hindsight score,
  baseline deltas, regret, exclusion reasons and completion status.
- **Evaluation run:** source/environment hashes, frozen data and label revisions,
  train/calibration/test dates, cohort and snapshot-selection rules, metric version,
  random seed, policy scenario, results and artifact paths.

Save private league/roster identities locally. A future public export should
allowlist aggregate metrics only. Run manifests must reproduce old results even
when subsequent box-score corrections arrive; a corrected evaluation is a new
revision, not a silent rewrite of the old scorecard.

## 5. Per-game projection scorecard

Choose the forecast revision **before viewing outcomes**. Primary product cohort:
the last successfully published forecast before the verified game deadline.
Keep all-day morning and one/two/several-day-ahead horizons as separate cohorts.
Late manual refreshes cannot cherry-pick the best of several forecasts. Unknown
timing or ambiguous game identity is excluded with a counted reason.

For error `e = actual FP − predicted FP`:

| Metric | Meaning |
| --- | --- |
| MAE: mean absolute error | Typical miss in this league's FP units; primary point-forecast measure |
| RMSE | Larger misses receive more weight |
| Signed bias: mean e | Positive means underprediction; negative means overprediction |
| Median and 90th-percentile absolute error | Typical and bad-tail misses without hiding outliers |
| Percentage within predeclared FP tolerances | Readable companion metric; define tolerance per formula before testing |
| Predictive interval coverage and width | Whether stated ranges contain outcomes at the advertised rate, and how broad they are |
| Quantile/pinball loss | Quality of saved lower/median/upper predictions, when available |
| Coverage | Eligible / forecasted / published on time / resolved / excluded counts, with reasons |

Repeat component errors for minutes, points, rebounds, assists, steals, blocks,
turnovers and shooting counters. Separate minutes error from per-minute production
error; actual-minutes substitutions are diagnostic counterfactuals, never valid
pregame inputs. Do not use percentage error as the headline metric: zero and
negative fantasy points make it misleading or undefined.

Current projections are conditional on playing. Score those against actual
appearances and show DNP, cancellation, missing-feed and unresolved rates
separately. Do not silently turn every unobserved result into zero. An unconditional
expected-value forecast requires an explicit, evaluated participation model; only
then can DNP=0 be a target under a documented product/scoring policy.

Compare the current model with last-game, trailing-five, season-to-date and
prior-season blended averages; only compare vendor forecasts where genuinely
archived. Evaluate each formula separately, then a clearly defined macro average
of relative improvement over B0, with zero-denominator cases marked undefined.
Keep identical player-games paired across candidates and report non-overlap/failure
coverage so a model cannot look better by skipping difficult players. Do not count
one NBA game repeated in five leagues as five independent observations.

Useful slices: sample size (0, 1–4, 5–9, 10+ current-season games), rookies,
prior-season bootstrap, source/fallback tier, forecast horizon, rest days, home/away,
minutes/role stability, injury returns and trades **only with evidence**, style,
opponent, formula and season. Display counts and uncertainty; avoid ranking a
player/model from a handful of games.

## 6. Weekly lock-policy scorecard

### Sequential replay and evidence classes

Use player × week × scoring-policy × decision-cadence as the unit. The primary
simulation is the actual daily publication cadence plus recorded manual updates;
separately test an ideal after-every-game cadence. Do not credit the daily app
with an opportunity it never published in time. Group complete weeks, including
all their player decisions, together in evaluation splits.

At each recorded eligible decision time:

1. Expose only observations/context available then and the current unexpired
   candidate score. Apply the frozen eligibility/deadline rules.
2. If already locked, retain that score and stop changing the policy result.
3. Otherwise run the frozen model. LOCK retains the candidate; WAIT advances;
   missing required inputs records an abstention rather than a guessed choice.
4. At week close, resolve only outcomes whose required games and rules are known.
   Record missed deadlines, DNPs and unresolved results explicitly.

The app does not import exact Sleeper lock deadlines or actual lock selections.
At kickoff, verify and version the applicable league rules, including whether an
old score remains selectable after the next game, final-score auto-lock behavior,
week boundaries and no-game/no-lock scoring. Until verified, use labeled
assumptions and report sensitivity scenarios; do not call them actual user results.
An assumed final-score fallback must not silently rescue a policy that waited too
long. If a verified rule scores no lock as zero, retain that zero and missed-lock
count; otherwise keep the primary terminal outcome unresolved and show scenarios.

Maintain three distinct result classes: **retrospective simulated policy**,
**prospective recommendation-following simulation**, and **actual user outcome**
(the last requires recorded selections). Frozen current rosters support a clearly
labeled current-roster cohort, not historical ownership. Player-only policy
benchmarks can use an NBA cohort without claiming full fantasy-team performance.

### Metrics and examples

- **Retained FP per eligible player-week**, total FP and paired difference from B0.
- **Regret:** best legally reachable hindsight FP minus retained FP, only for
  resolved outcomes under the same constraints. Hindsight is an upper-bound
  diagnostic, not a deployable strategy. Include a no-lock option only if legal.
- **Best-game hit rate**, with ties accepted; **within-tolerance rate** adds useful
  context when a policy misses the weekly best by very little.
- **Lock timing:** game index and remaining opportunities when selected; separate
  no-future-game forced choices from meaningful discretionary choices.
- **Premature lock cost:** subsequent legally reachable improvement forgone.
- **Wait cost:** a passed-over score exceeded the ultimately retained result.
- **Operational coverage:** eligible/resolved/abstained/missed-deadline/no-appearance
  weeks, with all policies assessed on the same predefined cohort.

Illustration only: a legal three-opportunity week scores 28, 46, 31 FP. Locking
46 retains 46 with zero regret; locking 28 leaves 18 FP; waiting through 46 and
retaining 31 leaves 15 FP. This is not a measured app result.

Compare first eligible game, final eligible opportunity where identifiable at
that time, a fixed pregame-baseline threshold, current B0, and the new candidate.
Give every policy identical timing, eligibility and terminal rules. A retrospectively
known "last appearance" is an oracle, not a valid last-scheduled-opportunity policy.
Avoid retained/best percentage as a headline measure because zero/negative FP can
make the ratio invalid. Lower game MAE alone cannot pass the weekly lock gate.

### Probability quality

Archive the raw `P(any later eligible performance > current score)` separately
from heuristic-adjusted `p_lock`. Score it with Brier loss, log loss and reliability
plots against that exact event, with strict greater-than for ties. Separate cases
with no later opportunities. Treat incomplete future evidence as unresolved.

If the original probability assumes all scheduled games are played, first evaluate
on complete-participation weeks, report that selection, and add a separate
all-eligible-week operational result with documented DNP semantics. Do not quietly
mix a participation-conditional probability with an unconditional target.
The adjusted lock score remains a heuristic until separately calibrated. Even a
well-calibrated beat-current probability does not by itself optimize retained FP;
future improvement magnitudes and sequential opportunities also matter.

## 7. ML experiments and safeguards

Start with metrics and reproducible baselines. Then, on the later branch:

1. Learn residual corrections or conditional error ranges from **out-of-fold**
   forecasts and pregame features. Begin with regularized regression; consider
   tree-based challengers only if they add held-out value.
2. Test sigmoid/isotonic calibration on a distinct, earlier calibration window
   when sample sizes justify it. Never calibrate on the final test outcomes.
3. Diagnose systematic misses by role/opponent/context. Feature importance is
   descriptive evidence, not proof of a causal matchup effect.
4. Tune decay, prior strength, opponent effects or lock thresholds only inside
   training/validation folds. Keep a frozen test and prospective shadow run.
5. Keep promotion manual: an error-learning job must never silently change live
   coefficients, recommendation thresholds or model versions.

Use chronological expanding or rolling date blocks. Keep all players in a game
and all forecasts for that game together. Lock labels mature at week end, so
purge training samples whose label windows overlap validation/test time. Fit all
imputation, scaling, feature selection and calibration within training boundaries.
Repeated players may span time blocks (the intended prediction task); include a
separate new-player evaluation where useful. A plain random player-row split is
not an honest test of future performance. TimeSeriesSplit is a conceptual starting
point; irregular NBA panels require explicit date/week grouping.

Use paired uncertainty intervals with date blocks for game errors and whole-week
blocks for policy outcomes. Preserve cross-player/game/formula correlations; use
longer blocks as a sensitivity check where dependence persists. Report repeated
searches and all meaningful regressions, not only the winning configuration.

The opponent epic's proposed promotion thresholds remain proposals. Before running
selection, agree separate gates for point error, probability calibration, weekly
retained FP/regret, coverage and resource cost. Freeze B0 without opponent effects;
compare opportunity-only, opponent-only and combined challengers to isolate gains.
An improvement requires credible held-out and prospective evidence, not merely
more data, a better training score or a successful pipeline.

## 8. Additional backend evaluations worth building

These are proposed scorecards, not existing instrumentation or measured results.

| Priority | Evaluation | Measures / experiment | What it catches |
| --- | --- | --- | --- |
| P0 | Information leakage and reproducibility | Future-input mutation checks, as-of joins, deterministic replay hashes, published-before-deadline rate | Unrealistic apparent accuracy |
| P0 | Provider/data quality | Expected final games reconciled, duplicate/missing rows, field coverage, identity ambiguity, correction size and cross-source disagreement | Bad inputs disguised as model misses |
| P0 | Freshness and publication reliability | Final-game → ingestion → report-visible lag; refresh/publish success, catch-up delay, stale hours and deadline misses | Good calculations arriving too late |
| P1 | Projection drift | Rolling bias/error, feature/missingness changes, interval coverage and source mix versus matched reference windows | Decay after trades, role changes or provider changes |
| P1 | Minutes / availability | Minutes MAE, conditional production error; participation Brier/reliability only with timestamped labels and predictions | Whether opportunity, not skill, causes errors |
| P1 | Lineup decision value | Actual FP versus legal hindsight optimum and simple forecast baselines on frozen eligible pools; slot violations and empty positions | Accurate predictions used badly by assignment logic |
| P1 | Pickup recommendation value | Frozen available/owned pools, fixed follow-up windows, realized improvement over proposed drop/hold and simple baselines, coverage | "On the rise" signals that vanish or were never claimable |
| P1 | Tail and milestone forecasts | Quantile loss/coverage, DD/TD and milestone Brier/reliability, bonus expectation error by league | Poor upside estimates even when mean FP looks good |
| P1 | Runtime and scaling | Cold/warm p50/p95 refresh stages, API calls/bytes, cache hit rate, DB rows scanned, peak memory, report size and publication time | Slowdowns as seasons/leagues/experiments grow |
| P1 | Failure recovery | Controlled provider timeout/429, partial input, interrupted writes, disk-full, delayed deployment and backup restore tests | Lost history, duplicate awards, silent stale reports |
| P2 | Recommendation stability | Forecast and lock flips between snapshots, changes attributable to new evidence, sensitivity to small input perturbations | Brittle decisions and threshold noise |
| P2 | Scoring / identity consistency | Same raw game rescored across formulas, approximation impact where full fields exist, traded-player/alias joins, unique forecast IDs | League-specific or identity-specific mistakes |
| P2 | Badge ledger correctness | Recompute subset vs stored counts, duplicate refresh and corrected-night audits, rule-version compatibility | Season leaderboard drift unrelated to model quality |
| P2 | Training/inference parity and cost | Offline-vs-live feature equality, model load/inference time, experiment duration/storage, fallback frequency | A research winner that cannot run reliably on the Mac |

Data-quality thresholds should use reconciled schedule/team evidence rather than
assuming every rostered player must have a box score. Pickup/lineup evaluation
requires historical ownership/eligibility snapshots; without them, label results
as hypothetical NBA-pool or fixed-roster studies. Availability needs an explicit
universe of candidates, not just the players who appeared in box scores.

Separate model regressions from ingestion/fallback changes and season schedule
mix. Drift notifications should require sufficient support and sustained change;
a single bad night is neither retraining evidence nor a production incident.
Benchmark a fixed machine/environment and representative multi-season/league loads;
set latency/memory budgets after measuring the baseline, not by inventing targets.
Fault injection must run against isolated temporary databases and test publishers.

## 9. Future app additions, in priority order

1. **Compact model scorecard:** recent game error, weekly FP retained/left behind,
   coverage and a comparison with B0, with drill-down rather than a vague accuracy %.
2. **Decision journal:** immutable recommendation, available alternatives and eventual
   outcome; distinguish model simulation from the user's actual choice.
3. **Forecast range and evidence label:** expected FP plus a validated range, sample
   size/source and stale-news context. Useful for volatile players and injury returns.
4. **What changed since refresh:** projection, availability, role and lineup changes
   with concrete reasons. Current vs previous snapshot comparison, not generated prose.
5. **Pickup follow-through:** track whether a suggested add improved the projected
   replacement over a predeclared window, once ownership snapshots exist.

Keep these under Season review or small disclosures; the roster sheet stays first.
No UI work is included in this proposal. First collect sound evidence, then expose
metrics that answer an actual user question.

## 10. Kickoff backlog and acceptance

| Stage | Deliverable | Acceptance |
| --- | --- | --- |
| EVAL-01 | Frozen definitions, cadence and league rule scenarios | Units, cohort, deadlines, terminal cases and metrics reviewed before tuning |
| EVAL-02 | Append-only forecast/decision archive and immutable run inputs | Idempotency, late forecasts, corrections, ambiguous IDs and replay provenance tested |
| EVAL-03 | Game-error backend and baseline report | Exact arithmetic fixtures, missing/DNP distinctions, paired coverage and reproducible folds |
| EVAL-04 | Weekly state machine and policy scorecard | No hindsight selection; early lock, ties, negatives, missed deadlines, DNP and final-week cases tested |
| EVAL-05 | Operational / quality benchmarks | Realistic fixed baseline measurements and isolated failure drills; publication remains independent |
| EVAL-06 | Opponent challengers, calibration and ML diagnostics | Separate evaluation, calibration and untouched test evidence; same inputs for B0/candidates |
| EVAL-07 | Prospective shadow collection | No live recommendation changes; actual publication timing and matured labels retained |
| EVAL-08 | Reviewable release proposal | Independent projection/lock gates, clear regressions, migrations/backup/rollback reviewed before merge |

Create the development branch only when the user starts this later work; choose
its name then. No implementation branch is created by writing this proposal.
Merge only after the agreed evidence and release review. Keep the current
production model available as an immediate fallback.

## References

Primary references used for method definitions; they do not establish this app's
accuracy or prescribe its product rules:

- [scikit-learn model evaluation](https://scikit-learn.org/stable/modules/model_evaluation.html): regression losses and probabilistic scoring.
- [scikit-learn probability calibration](https://scikit-learn.org/stable/modules/calibration.html): reliability diagrams and calibration methods; Brier/log loss measure more than calibration alone.
- [scikit-learn TimeSeriesSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html): chronological splitting, with additional grouping required here.
- [scikit-learn common pitfalls](https://scikit-learn.org/stable/common_pitfalls.html): preprocessing and leakage prevention.
- [Current replay limitations](../HISTORICAL_REPLAY.md) and [current architecture](../ARCHITECTURE.md).
