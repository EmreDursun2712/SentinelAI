"""Classification metrics + confusion-matrix serialization."""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)


def compute_metrics(
    y_true: np.ndarray, y_pred: np.ndarray, classes: list[str]
) -> dict[str, Any]:
    """Return a JSON-friendly dict of scalar + per-class metrics."""
    labels = list(range(len(classes)))
    report = classification_report(
        y_true,
        y_pred,
        labels=labels,
        target_names=classes,
        zero_division=0,
        output_dict=True,
    )

    return {
        "precision_macro": float(
            precision_score(y_true, y_pred, average="macro", zero_division=0)
        ),
        "recall_macro": float(
            recall_score(y_true, y_pred, average="macro", zero_division=0)
        ),
        "f1_macro": float(f1_score(y_true, y_pred, average="macro", zero_division=0)),
        "precision_weighted": float(
            precision_score(y_true, y_pred, average="weighted", zero_division=0)
        ),
        "recall_weighted": float(
            recall_score(y_true, y_pred, average="weighted", zero_division=0)
        ),
        "f1_weighted": float(
            f1_score(y_true, y_pred, average="weighted", zero_division=0)
        ),
        "accuracy": float(np.mean(np.asarray(y_true) == np.asarray(y_pred))),
        "support": int(len(y_true)),
        "per_class": _strip_numpy(report),
    }


def confusion_matrix_json(
    y_true: np.ndarray, y_pred: np.ndarray, classes: list[str]
) -> dict[str, Any]:
    cm = confusion_matrix(y_true, y_pred, labels=range(len(classes)))
    return {"labels": classes, "matrix": cm.tolist()}


def _strip_numpy(obj: Any) -> Any:
    """Recursively convert numpy scalars to native Python types for json.dumps."""
    if isinstance(obj, dict):
        return {k: _strip_numpy(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_numpy(v) for v in obj]
    if isinstance(obj, np.generic):
        return obj.item()
    return obj
