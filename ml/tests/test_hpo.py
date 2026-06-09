"""Hyperparameter-search helper tests."""

from __future__ import annotations

import pytest

from ml.hpo import param_space_for, run_search
from ml.pipeline import build_pipeline
from ml.synthetic import FEATURES, generate


def _xy(n: int = 800):
    df = generate(n, random_state=0, nan_rate=0.0, inf_rate=0.0)
    return df[list(FEATURES)], df["label"]


def test_param_space_known_algorithms() -> None:
    assert "classifier__n_estimators" in param_space_for("random_forest")
    assert "classifier__learning_rate" in param_space_for("gradient_boosting")
    with pytest.raises(ValueError):
        param_space_for("unknown")


def test_run_search_none_is_passthrough() -> None:
    pipe = build_pipeline(n_estimators=10)
    out, record = run_search(pipe, None, None, algorithm="random_forest", mode="none")
    assert out is pipe
    assert record == {"mode": "none"}


def test_run_search_random_records_best_params() -> None:
    X, y = _xy()
    pipe = build_pipeline(algorithm="random_forest", n_estimators=20)
    best, record = run_search(
        pipe, X, y, algorithm="random_forest", mode="random", n_iter=3, cv=2, random_state=1
    )
    assert record["mode"] == "random"
    assert record["n_candidates"] == 3
    assert 0.0 <= record["best_score"] <= 1.0
    assert record["best_params"]  # non-empty
    # Best estimator is fitted and usable.
    assert best.predict(X.head(3)).shape[0] == 3


def test_run_search_best_params_are_jsonable() -> None:
    import json

    X, y = _xy(600)
    pipe = build_pipeline(algorithm="random_forest", n_estimators=20)
    _, record = run_search(
        pipe, X, y, algorithm="random_forest", mode="random", n_iter=2, cv=2, random_state=2
    )
    # Must serialize cleanly for metadata.json.
    json.dumps(record)
