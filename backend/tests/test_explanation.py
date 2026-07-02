"""Per-prediction explanation (tree-path decomposition) unit tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline

from app.services.explanation_service import explain_prediction
from app.services.model_registry import ModelBundle

FEATURES = ["a", "b"]
CLASSES = ["BENIGN", "ATTACK"]


def _training_data(n: int = 400, seed: int = 0):
    """'a' cleanly separates the classes; 'b' is pure noise."""
    rng = np.random.default_rng(seed)
    a = rng.normal(size=n)
    b = rng.normal(size=n)  # noise
    y = (a > 0).astype(int)  # 0 == BENIGN, 1 == ATTACK
    # Fit on a named frame (as production does via build_xy) so the imputer keeps
    # feature names and inference doesn't warn.
    X = pd.DataFrame({"a": a, "b": b}, columns=FEATURES)
    return X, y


def _bundle(pipeline) -> ModelBundle:
    return ModelBundle(
        pipeline=pipeline,
        metadata={"name": "t", "version": "v0", "algorithm": "random_forest"},
        classes=list(CLASSES),
        feature_order=list(FEATURES),
        name="t",
        version="v0",
        algorithm="random_forest",
        artifact_dir=Path("/tmp/t"),
        loaded_at=datetime.now(UTC),
    )


def _plain_pipeline() -> Pipeline:
    X, y = _training_data()
    pipe = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("classifier", RandomForestClassifier(n_estimators=40, random_state=0)),
        ]
    )
    pipe.fit(X, y)
    return pipe


def test_additive_decomposition_matches_forest_probability() -> None:
    # For an *uncalibrated* forest, base_value + Σ contributions == the served
    # probability exactly (that's the identity the tree-path method guarantees).
    bundle = _bundle(_plain_pipeline())
    exp = explain_prediction(bundle, {"a": 2.5, "b": -0.3}, "ATTACK", top_k=2)
    assert exp is not None
    assert exp.explained_class == "ATTACK"
    assert exp.model_probability is not None
    assert exp.contribution_sum == pytest.approx(exp.model_probability, abs=1e-6)


def test_informative_feature_dominates_contribution() -> None:
    bundle = _bundle(_plain_pipeline())
    exp = explain_prediction(bundle, {"a": 2.5, "b": -0.3}, "ATTACK", top_k=2)
    assert exp is not None
    top = max(exp.contributions, key=lambda c: abs(c.contribution))
    assert top.feature == "a"  # the separating feature, not the noise 'b'
    assert top.contribution > 0  # a large positive 'a' pushes toward ATTACK
    assert top.value == 2.5  # the (pre-imputation) input value is echoed back


def test_missing_feature_value_is_reported_as_none() -> None:
    bundle = _bundle(_plain_pipeline())
    exp = explain_prediction(bundle, {"a": 2.5}, "ATTACK", top_k=2)  # 'b' missing
    assert exp is not None
    b_item = next((c for c in exp.contributions if c.feature == "b"), None)
    if b_item is not None:
        assert b_item.value is None  # imputed → original value unknown


def test_calibrated_model_is_explained() -> None:
    X, y = _training_data()
    base = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("classifier", RandomForestClassifier(n_estimators=40, random_state=0)),
        ]
    )
    cal = CalibratedClassifierCV(base, method="sigmoid", cv=3)
    cal.fit(X, y)
    bundle = _bundle(cal)
    exp = explain_prediction(bundle, {"a": 2.5, "b": -0.3}, "ATTACK", top_k=2)
    assert exp is not None
    assert exp.contributions
    # Contributions aggregate across all calibration folds' forests.
    top = max(exp.contributions, key=lambda c: abs(c.contribution))
    assert top.feature == "a"


def test_unknown_label_returns_none() -> None:
    bundle = _bundle(_plain_pipeline())
    assert explain_prediction(bundle, {"a": 1.0, "b": 1.0}, "NOT_A_CLASS") is None


def test_non_forest_model_returns_none() -> None:
    class _Dummy:
        classes_ = np.array([0, 1])

        def predict_proba(self, X):
            return np.tile([0.5, 0.5], (len(X), 1))

    bundle = _bundle(_Dummy())
    assert explain_prediction(bundle, {"a": 1.0, "b": 1.0}, "ATTACK") is None
