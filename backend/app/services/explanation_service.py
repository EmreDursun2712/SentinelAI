"""Per-prediction explainability for the detection model.

The investigation packet historically carried only *global* feature importance
(``RandomForest.feature_importances_``) — "which features matter to the model
overall", not "why was *this* alert assigned *this* class". This service adds the
local, per-prediction view via the exact tree-path decomposition (the "Saabas" /
TreeInterpreter method that TreeSHAP builds on): every tree's prediction is
walked from root to leaf and the change in the class probability at each split is
attributed to the splitting feature, so

    P(class | x)  ==  base_value  +  Σ_feature  contribution(feature)

holds exactly for the averaged forest. It's dependency-free (no ``shap`` /
``numba`` — which matters given the pinned ``scikit-learn`` and the slim backend
image) and works on both the plain ``Pipeline`` and the ``CalibratedClassifierCV``
the calibrated model ships as (contributions are aggregated over every base
forest across the calibration folds).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.core.logging import get_logger
from app.services.detection_service import build_feature_matrix
from app.services.model_registry import ModelBundle

logger = get_logger(__name__)


@dataclass
class FeatureContribution:
    feature: str
    value: float | None  # the (pre-imputation) input value; None when missing
    contribution: float  # signed push toward the explained class


@dataclass
class PredictionExplanation:
    method: str
    explained_class: str
    base_value: float  # forest's average root probability for the class
    contribution_sum: float  # base_value + Σ contributions == forest probability
    model_probability: float | None  # the served (calibrated) probability
    contributions: list[FeatureContribution] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Model introspection — pull the (imputer, forest) base learners out of whatever
# the pipeline actually is.
# ---------------------------------------------------------------------------


def _is_forest(estimator: Any) -> bool:
    """A tree ensemble we can path-decompose: has ``estimators_`` of ``tree_``."""
    trees = getattr(estimator, "estimators_", None)
    if trees is None or len(trees) == 0:
        return False
    return hasattr(trees[0], "tree_") and hasattr(estimator, "classes_")


def _base_learners(pipeline: Any) -> list[tuple[Any, Any]]:
    """Return ``[(imputer_or_None, forest), ...]`` extracted from ``pipeline``.

    Handles a plain ``Pipeline(imputer, classifier)``, a bare forest, and a
    ``CalibratedClassifierCV`` (one base pipeline per calibration fold).
    """
    learners: list[tuple[Any, Any]] = []

    calibrated = getattr(pipeline, "calibrated_classifiers_", None)
    if calibrated is not None:
        for cc in calibrated:
            est = getattr(cc, "estimator", None)
            learners.extend(_base_learners(est) if est is not None else [])
        return learners

    named = getattr(pipeline, "named_steps", None)
    if named is not None:
        clf = named.get("classifier")
        if clf is not None and _is_forest(clf):
            learners.append((named.get("imputer"), clf))
        return learners

    if _is_forest(pipeline):
        learners.append((None, pipeline))
    return learners


# ---------------------------------------------------------------------------
# Exact tree-path decomposition.
# ---------------------------------------------------------------------------


def _tree_contributions(tree: Any, x: np.ndarray, class_pos: int) -> tuple[float, np.ndarray]:
    """``(base, contrib)`` for one decision tree, one sample, one class column.

    ``base`` is the root's probability for the class; ``contrib[f]`` sums the
    per-split probability change attributed to feature ``f`` along the decision
    path. ``base + contrib.sum()`` equals the leaf probability.
    """
    t = tree.tree_
    # value: (n_nodes, 1, n_classes) class counts → per-node probability vector.
    counts = t.value[:, 0, :]
    totals = counts.sum(axis=1, keepdims=True)
    totals[totals == 0] = 1.0
    probs = counts / totals

    contrib = np.zeros(x.shape[0], dtype=float)
    node = 0
    base = float(probs[0, class_pos])
    left, right = t.children_left, t.children_right
    feat, thr = t.feature, t.threshold
    while left[node] != -1:  # -1 == _tree.TREE_LEAF → this node is internal
        f = feat[node]
        child = left[node] if x[f] <= thr[node] else right[node]
        contrib[f] += float(probs[child, class_pos] - probs[node, class_pos])
        node = child
    return base, contrib


def explain_prediction(
    bundle: ModelBundle,
    features: dict[str, Any],
    predicted_label: str,
    *,
    top_k: int = 12,
) -> PredictionExplanation | None:
    """Explain why ``bundle`` assigned ``predicted_label`` to ``features``.

    Returns ``None`` when the model isn't a supported tree ensemble or the label
    isn't in the model's class space (nothing to attribute).
    """
    try:
        class_encoded = bundle.classes.index(predicted_label)
    except ValueError:
        return None

    learners = _base_learners(bundle.pipeline)
    if not learners:
        return None

    feature_order = bundle.feature_order
    # 1-row frame in training column order (missing keys → NaN). Kept as a
    # DataFrame so the fitted imputer sees the feature names it expects (no
    # sklearn "valid feature names" warning on every alert).
    X_df = build_feature_matrix([features], feature_order)
    x_raw = X_df.to_numpy(dtype=float)[0]

    total_bias = 0.0
    total_contrib = np.zeros(len(feature_order), dtype=float)
    n_trees = 0
    for imputer, forest in learners:
        pos_arr = np.where(np.asarray(forest.classes_) == class_encoded)[0]
        if pos_arr.size == 0:
            continue  # this fold never saw the class — skip
        class_pos = int(pos_arr[0])
        x_imp = imputer.transform(X_df)[0] if imputer is not None else x_raw
        for tree in forest.estimators_:
            base, contrib = _tree_contributions(tree, x_imp, class_pos)
            total_bias += base
            total_contrib += contrib
            n_trees += 1

    if n_trees == 0:
        return None

    mean_bias = total_bias / n_trees
    mean_contrib = total_contrib / n_trees

    # The actually-served probability (calibrated, if the model is) for context.
    model_prob: float | None = None
    try:
        proba = np.asarray(bundle.pipeline.predict_proba(X_df))[0]
        model_prob = float(proba[class_encoded])
    except Exception:  # pragma: no cover - defensive
        model_prob = None

    order = np.argsort(np.abs(mean_contrib))[::-1][:top_k]
    contributions: list[FeatureContribution] = []
    for idx in order:
        if mean_contrib[idx] == 0.0:
            continue
        raw = x_raw[idx]
        contributions.append(
            FeatureContribution(
                feature=feature_order[idx],
                value=None if not np.isfinite(raw) else round(float(raw), 4),
                contribution=round(float(mean_contrib[idx]), 6),
            )
        )

    return PredictionExplanation(
        method="tree_path",
        explained_class=predicted_label,
        base_value=round(float(mean_bias), 6),
        contribution_sum=round(float(mean_bias + mean_contrib.sum()), 6),
        model_probability=round(model_prob, 6) if model_prob is not None else None,
        contributions=contributions,
    )
