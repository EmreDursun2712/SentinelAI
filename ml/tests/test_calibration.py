"""Probability-calibration helper tests."""

from __future__ import annotations

import numpy as np

from ml.calibration import (
    calibrate_pipeline,
    calibration_report,
    multiclass_brier_score,
    reliability_curve,
)
from ml.pipeline import build_pipeline
from ml.synthetic import FEATURES, generate


def test_multiclass_brier_perfect_is_zero() -> None:
    y = np.array([0, 1, 2])
    proba = np.eye(3)
    assert multiclass_brier_score(y, proba, 3) == 0.0


def test_multiclass_brier_worst_case() -> None:
    # Fully confident but always wrong: each row contributes (1)^2 + (1)^2 = 2.
    y = np.array([0, 0])
    proba = np.array([[0.0, 1.0], [0.0, 1.0]])
    assert multiclass_brier_score(y, proba, 2) == 2.0


def test_reliability_curve_bins_confidence_vs_accuracy() -> None:
    y = np.array([1, 1, 0, 0])
    proba = np.array([[0.1, 0.9], [0.2, 0.8], [0.95, 0.05], [0.6, 0.4]])
    curve = reliability_curve(y, proba, n_bins=10)
    assert len(curve["mean_confidence"]) == len(curve["accuracy"]) == len(curve["count"])
    assert sum(curve["count"]) == 4
    # All four predictions are correct here, so every populated bin has accuracy 1.
    assert all(a == 1.0 for a in curve["accuracy"])


def test_reliability_curve_handles_empty() -> None:
    curve = reliability_curve(np.array([]), np.empty((0, 2)))
    assert curve == {"mean_confidence": [], "accuracy": [], "count": []}


def test_calibration_report_shape() -> None:
    y = np.array([0, 1, 1, 0])
    proba = np.array([[0.7, 0.3], [0.2, 0.8], [0.4, 0.6], [0.9, 0.1]])
    report = calibration_report(y, proba, ["BENIGN", "DDoS"], method="sigmoid")
    assert report["method"] == "sigmoid"
    assert report["calibrated"] is True
    assert "brier_score" in report and report["brier_score"] >= 0.0
    assert "reliability_curve" in report


def test_calibration_report_none_marks_uncalibrated() -> None:
    y = np.array([0, 1])
    proba = np.array([[0.8, 0.2], [0.3, 0.7]])
    report = calibration_report(y, proba, ["A", "B"], method="none")
    assert report["calibrated"] is False


def test_calibrate_pipeline_returns_probabilistic_estimator() -> None:
    df = generate(1200, random_state=0, nan_rate=0.0, inf_rate=0.0)
    X = df[list(FEATURES)]
    y = df["label"]
    base = build_pipeline(algorithm="random_forest", n_estimators=40)
    calibrated = calibrate_pipeline(base, X, y, method="sigmoid", cv=3)
    proba = calibrated.predict_proba(X.head(5))
    assert proba.shape[0] == 5
    # Rows of a probability matrix sum to 1.
    assert np.allclose(proba.sum(axis=1), 1.0, atol=1e-6)


def test_calibrate_none_is_passthrough() -> None:
    base = build_pipeline(algorithm="random_forest", n_estimators=10)
    assert calibrate_pipeline(base, None, None, method="none") is base
