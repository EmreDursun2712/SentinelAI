"""Optional probability calibration for the detection pipeline.

A Random Forest's ``predict_proba`` is not a well-calibrated probability — the
top value is what the detection threshold compares against, so miscalibration
biases the alert rate. ``--calibrate {sigmoid,isotonic}`` wraps the fitted
pipeline in :class:`~sklearn.calibration.CalibratedClassifierCV` so the backend's
confidence (and therefore the alerting decision) reflects calibrated probability.

We also compute evaluation diagnostics — a multiclass Brier score and a
reliability curve (binned confidence vs. empirical accuracy) — persisted to
``metadata.json`` under ``calibration`` so the improvement is auditable.
"""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
from sklearn.base import clone
from sklearn.calibration import CalibratedClassifierCV
from sklearn.pipeline import Pipeline

CalibrationMethod = Literal["none", "sigmoid", "isotonic"]


def calibrate_pipeline(
    pipeline: Pipeline,
    X: Any,
    y: Any,
    *,
    method: CalibrationMethod,
    cv: int = 3,
) -> Pipeline:
    """Return a calibrated clone of ``pipeline`` fitted on ``(X, y)``.

    Uses ``CalibratedClassifierCV`` with internal cross-validation, so the
    estimator is both fit and calibrated on the training split (no separate
    holdout needed). ``method="none"`` returns the input pipeline unchanged.
    """
    if method == "none":
        return pipeline
    base = clone(pipeline)
    calibrated = CalibratedClassifierCV(base, method=method, cv=cv)
    calibrated.fit(X, y)
    return calibrated


def multiclass_brier_score(y_true: np.ndarray, proba: np.ndarray, n_classes: int) -> float:
    """Mean squared error between predicted probability vectors and one-hot truth.

    The standard multiclass generalization of the Brier score: lower is better,
    ``0`` is perfect. ``y_true`` holds integer class indices; ``proba`` is the
    ``(n_samples, n_classes)`` probability matrix.
    """
    y_true = np.asarray(y_true)
    proba = np.asarray(proba, dtype=float)
    onehot = np.zeros((len(y_true), n_classes), dtype=float)
    onehot[np.arange(len(y_true)), y_true] = 1.0
    return float(np.mean(np.sum((proba - onehot) ** 2, axis=1)))


def reliability_curve(
    y_true: np.ndarray, proba: np.ndarray, *, n_bins: int = 10
) -> dict[str, list[float]]:
    """Binned top-confidence vs. empirical accuracy (a calibration curve).

    For each predicted sample we take the top class + its probability, bucket by
    that probability into ``n_bins`` equal-width bins over [0, 1], and report the
    mean confidence and mean accuracy per non-empty bin. A perfectly calibrated
    model lies on the diagonal (confidence == accuracy).
    """
    proba = np.asarray(proba, dtype=float)
    y_true = np.asarray(y_true)
    if proba.size == 0:
        return {"mean_confidence": [], "accuracy": [], "count": []}

    top_idx = np.argmax(proba, axis=1)
    top_conf = proba[np.arange(len(proba)), top_idx]
    correct = (top_idx == y_true).astype(float)

    edges = np.linspace(0.0, 1.0, n_bins + 1)
    # Indices 0..n_bins-1; the final edge is inclusive via clip.
    bin_idx = np.clip(np.digitize(top_conf, edges[1:-1], right=False), 0, n_bins - 1)

    mean_conf: list[float] = []
    accuracy: list[float] = []
    counts: list[float] = []
    for b in range(n_bins):
        mask = bin_idx == b
        n = int(mask.sum())
        if n == 0:
            continue
        mean_conf.append(round(float(top_conf[mask].mean()), 4))
        accuracy.append(round(float(correct[mask].mean()), 4))
        counts.append(n)
    return {"mean_confidence": mean_conf, "accuracy": accuracy, "count": counts}


def calibration_report(
    y_true: np.ndarray,
    proba: np.ndarray,
    classes: list[str],
    *,
    method: CalibrationMethod,
    n_bins: int = 10,
) -> dict[str, Any]:
    """Build the JSON ``calibration`` block stored in metadata."""
    return {
        "method": method,
        "calibrated": method != "none",
        "brier_score": multiclass_brier_score(y_true, proba, len(classes)),
        "reliability_curve": reliability_curve(y_true, proba, n_bins=n_bins),
    }
