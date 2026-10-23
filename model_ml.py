"""Closed-form Ridge component model for opponent-aware player projections.

Each box-score component (PTS, REB, AST, STL, BLK, TOV, FG3M) gets its own
Ridge regression beta = (X^T X + lambda I)^-1 X^T y over the feature vector
defined in features.py. Predictions are clamped to nonnegative values and
rescored through scoring.add_fantasy_points, so any league formula — weights,
double/triple-double and milestone bonuses — applies unchanged.

Training and inference are deterministic NumPy linear algebra with no network
calls and no new dependencies.
"""

import numpy as np
import pandas as pd

from fetch_data import normalize_stats_for_scoring
from features import COMPONENTS
from scoring import add_fantasy_points

DEFAULT_LAMBDA = 10.0
RESIDUAL_STD_FLOOR = 1.0

# Knobs adjustable under cfg["model"] — retune via `evaluator.py --mode tune`.
_MODEL_KNOBS = {
    "ridge_lambda": (float, DEFAULT_LAMBDA),
    "feature_window": (int, 15),
    "player_decay": (float, 0.92),
    "player_lookback": (int, 10),
    "min_player_games": (int, 5),
    "min_train_rows": (int, 100),
}


def model_settings(cfg):
    """Effective opponent-model knobs: cfg['model'] overrides, else defaults."""
    mp = (cfg or {}).get("model") or {}
    out = {}
    for key, (cast, default) in _MODEL_KNOBS.items():
        try:
            out[key] = cast(mp.get(key, default))
        except (TypeError, ValueError):
            out[key] = default
    return out


def feature_columns(stat):
    """Feature vector for one component, per the runbook spec."""
    return [
        f"recent_mean_{stat}",
        f"season_mean_{stat}",
        "recent_min",
        "pace_mult",
        "defrtg_rel",
        f"pos_ratio_{stat}",
        "is_home",
        "b2b",
    ]


def ridge_fit(X, y, lam=DEFAULT_LAMBDA):
    """Closed-form Ridge: beta = (X'X + lam I)^-1 X'y, intercept unpenalized."""
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = np.isfinite(X).all(axis=1) & np.isfinite(y)
    X, y = X[mask], y[mask]
    if len(X) == 0:
        return np.zeros(X.shape[1] + 1 if X.ndim == 2 else 1)
    Xd = np.column_stack([np.ones(len(X)), X])
    penalty = lam * np.eye(Xd.shape[1])
    penalty[0, 0] = 0.0  # never shrink the intercept
    return np.linalg.solve(Xd.T @ Xd + penalty, Xd.T @ y)


def ridge_predict(X, beta):
    X = np.asarray(X, dtype=float)
    X = np.where(np.isfinite(X), X, 0.0)
    Xd = np.column_stack([np.ones(len(X)), X])
    return np.maximum(Xd @ beta, 0.0)


class ComponentRidge:
    """One Ridge regression per box-score component plus an FP residual scale."""

    def __init__(self, lam=DEFAULT_LAMBDA):
        self.lam = float(lam)
        self.betas = {}
        self.fp_resid_std = np.nan
        self.n_train = 0

    def fit(self, frame, weights=None):
        """Fit each component on a feature matrix produced by FeatureBuilder.

        ``frame`` must contain the feature columns plus the actual component
        targets. When ``weights`` are supplied, in-sample fantasy-point
        residuals are stored as ``fp_resid_std`` for downstream probabilities.
        """
        self.n_train = len(frame)
        for stat in COMPONENTS:
            cols = feature_columns(stat)
            missing = [c for c in cols if c not in frame]
            if missing or stat not in frame:
                self.betas[stat] = np.zeros(len(cols) + 1)
                continue
            X = frame[cols].to_numpy(dtype=float)
            y = frame[stat].to_numpy(dtype=float)
            self.betas[stat] = ridge_fit(X, y, self.lam)
        if weights is not None and len(frame):
            predicted = self.predict_fp(frame, weights)
            actual = add_fantasy_points(normalize_stats_for_scoring(frame), weights).FP
            resid = (actual.reindex(frame.index) - predicted).to_numpy(dtype=float)
            resid = resid[np.isfinite(resid)]
            self.fp_resid_std = (
                float(np.std(resid, ddof=1)) if resid.size > 1 else np.nan
            )
            if np.isfinite(self.fp_resid_std):
                self.fp_resid_std = max(self.fp_resid_std, RESIDUAL_STD_FLOOR)
        return self

    def predict_components(self, frame):
        """Nonnegative predictions for each component, aligned to ``frame``."""
        out = pd.DataFrame(index=frame.index)
        for stat in COMPONENTS:
            beta = self.betas.get(stat)
            cols = feature_columns(stat)
            if (
                beta is None
                or not np.isfinite(beta).all()
                or not all(c in frame for c in cols)
            ):
                out[stat] = 0.0
                continue
            out[stat] = ridge_predict(frame[cols], beta)
        return out

    def predict_fp(self, frame, weights):
        """Predict components, then rescore through the league's own formula."""
        stats = self.predict_components(frame)
        scored_input = pd.DataFrame(index=frame.index)
        scored_input["PLAYER_ID"] = (
            frame.PLAYER_ID.astype(str)
            if "PLAYER_ID" in frame
            else [str(i) for i in range(len(frame))]
        )
        scored_input["GAME_DATE"] = frame.GAME_DATE
        scored_input["MIN"] = (
            pd.to_numeric(frame["recent_min"], errors="coerce")
            if "recent_min" in frame
            else 0.0
        )
        for stat in COMPONENTS:
            scored_input[stat] = stats[stat].to_numpy(dtype=float)
        scored = add_fantasy_points(normalize_stats_for_scoring(scored_input), weights)
        # parse_dates sorts by GAME_DATE; restore the caller's row order.
        return scored.FP.reindex(frame.index)
