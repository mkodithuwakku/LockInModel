import numpy as np
import pandas as pd
import pytest

from features import COMPONENTS, FeatureBuilder
from model_ml import ComponentRidge, feature_columns, ridge_fit, ridge_predict
from test_features import two_team_game


def test_ridge_recovers_known_linear_relation():
    rng = np.random.default_rng(7)
    X = rng.normal(size=(400, 3))
    beta_true = np.array([2.0, -1.0, 0.5])
    y = 3.0 + X @ beta_true
    beta = ridge_fit(X, y, lam=1e-8)
    assert beta[0] == pytest.approx(3.0, abs=1e-4)
    assert np.allclose(beta[1:], beta_true, atol=1e-4)
    # Clamp only affects the (nonnegative) stat domain, not the raw fit.
    assert np.allclose(np.maximum(beta[0] + X @ beta[1:], 0.0), ridge_predict(X, beta))


def test_ridge_is_deterministic_and_stable_on_collinear_data():
    X = np.tile(np.linspace(0, 1, 50), (2, 1)).T  # perfectly collinear columns
    y = np.linspace(0, 10, 50)
    beta = ridge_fit(X, y, lam=10.0)
    beta_again = ridge_fit(X, y, lam=10.0)
    assert np.all(np.isfinite(beta))
    assert np.array_equal(beta, beta_again)


def test_predictions_are_clamped_nonnegative():
    model = ComponentRidge()
    model.betas = {s: np.full(len(feature_columns(s)) + 1, -5.0) for s in COMPONENTS}
    frame = pd.DataFrame({c: [1.0, 2.0] for c in feature_columns("PTS")})
    out = model.predict_components(frame)
    assert (out.to_numpy() >= 0).all()


def _synthetic_games(days=6):
    for i in range(days):
        date = f"2025-11-{3 + i:02d}"
        for r in two_team_game(f"g{i}", date, pts=10 + i, min_=24.0 + i):
            yield r


def test_component_model_fit_predicts_and_rescoring_uses_league_formula():
    games = pd.DataFrame(list(_synthetic_games()))
    builder = FeatureBuilder(games)
    matrix = builder.training_matrix()
    model = ComponentRidge().fit(matrix, weights={"PTS": 1.0, "REB": 0.5})
    preds = model.predict_components(matrix)
    assert set(preds.columns) == set(COMPONENTS)
    assert (preds.to_numpy() >= 0).all()
    assert np.isfinite(model.fp_resid_std) and model.fp_resid_std >= 1.0
    fp = model.predict_fp(matrix, {"PTS": 1.0, "REB": 0.5})
    # With PTS weight 1 and REB weight 0.5 the league formula is applied to
    # the predicted components.
    assert np.allclose(fp.to_numpy(), preds.PTS + 0.5 * preds.REB)


def test_fit_on_empty_or_missing_features_degrades_gracefully():
    model = ComponentRidge().fit(pd.DataFrame(), {"PTS": 1.0})
    frame = pd.DataFrame({"PLAYER_ID": ["x"], "GAME_DATE": ["2025-11-03"]})
    out = model.predict_components(frame)
    assert (out.to_numpy() == 0).all()
    fp = model.predict_fp(frame, {"PTS": 1.0})
    assert fp.iloc[0] == 0.0


def test_model_settings_defaults_and_cfg_overrides():
    from model_ml import model_settings

    defaults = model_settings(None)
    assert defaults["ridge_lambda"] == 10.0
    assert defaults["feature_window"] == 15
    assert defaults["player_decay"] == pytest.approx(0.92)
    assert defaults["player_lookback"] == 10
    assert defaults["min_player_games"] == 5
    assert defaults["min_train_rows"] == 100
    tuned = model_settings(
        {
            "model": {
                "ridge_lambda": 50.0,
                "feature_window": 25,
                "player_decay": "0.95",
                "min_player_games": "bogus",
            }
        }
    )
    assert tuned["ridge_lambda"] == 50.0
    assert tuned["feature_window"] == 25
    assert tuned["player_decay"] == pytest.approx(0.95)
    assert tuned["min_player_games"] == 5  # invalid values keep the default
