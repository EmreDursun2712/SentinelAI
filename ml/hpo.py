"""Optional hyperparameter optimization for the detection pipeline.

Off by default — normal training stays fast. ``--search random`` (or ``grid``)
runs a cross-validated search over a small, sensible grid for the chosen
algorithm and returns the best estimator plus a JSON-friendly record of what was
tried (persisted to ``metadata.json`` under ``hpo``).

The search operates on the *whole* ``Pipeline`` (imputer + classifier), so
parameters are addressed with the ``classifier__`` prefix. We optimize macro-F1
to match how the model is scored elsewhere (class-imbalance aware).
"""

from __future__ import annotations

from typing import Any, Literal

from sklearn.model_selection import GridSearchCV, RandomizedSearchCV
from sklearn.pipeline import Pipeline

SearchMode = Literal["none", "random", "grid"]


# Per-algorithm parameter spaces, addressed through the Pipeline's ``classifier``
# step. Kept deliberately small so a search finishes in seconds-to-minutes on a
# laptop; widen these if you have the compute.
PARAM_SPACES: dict[str, dict[str, list[Any]]] = {
    "random_forest": {
        "classifier__n_estimators": [100, 200, 400],
        "classifier__max_depth": [None, 12, 24],
        "classifier__min_samples_leaf": [1, 2, 4],
        "classifier__max_features": ["sqrt", "log2"],
    },
    "gradient_boosting": {
        "classifier__n_estimators": [100, 200],
        "classifier__max_depth": [2, 3],
        "classifier__learning_rate": [0.05, 0.1, 0.2],
    },
}


def param_space_for(algorithm: str) -> dict[str, list[Any]]:
    if algorithm not in PARAM_SPACES:
        raise ValueError(f"No HPO space defined for algorithm {algorithm!r}")
    return PARAM_SPACES[algorithm]


def run_search(
    pipeline: Pipeline,
    X: Any,
    y: Any,
    *,
    algorithm: str,
    mode: SearchMode,
    n_iter: int = 20,
    cv: int = 3,
    random_state: int = 42,
    n_jobs: int = -1,
) -> tuple[Pipeline, dict[str, Any]]:
    """Search hyperparameters and return ``(best_pipeline, record)``.

    ``record`` always has ``mode``; for an actual search it also carries
    ``best_params``, ``best_score`` (mean CV macro-F1), ``n_candidates``, ``cv``,
    and ``scoring``. ``mode="none"`` short-circuits: the input pipeline is
    returned unchanged with ``record={"mode": "none"}``.
    """
    if mode == "none":
        return pipeline, {"mode": "none"}

    space = param_space_for(algorithm)
    scoring = "f1_macro"

    if mode == "grid":
        search: GridSearchCV | RandomizedSearchCV = GridSearchCV(
            pipeline, space, scoring=scoring, cv=cv, n_jobs=n_jobs, refit=True
        )
    elif mode == "random":
        search = RandomizedSearchCV(
            pipeline,
            space,
            n_iter=n_iter,
            scoring=scoring,
            cv=cv,
            n_jobs=n_jobs,
            random_state=random_state,
            refit=True,
        )
    else:  # pragma: no cover - guarded by argparse choices
        raise ValueError(f"Unknown search mode {mode!r}")

    search.fit(X, y)
    record = {
        "mode": mode,
        "scoring": scoring,
        "cv": cv,
        "n_candidates": len(search.cv_results_["params"]),
        "best_score": float(search.best_score_),
        "best_params": {k: _jsonable(v) for k, v in search.best_params_.items()},
    }
    if mode == "random":
        record["n_iter"] = n_iter
    return search.best_estimator_, record


def _jsonable(value: Any) -> Any:
    """Coerce search params (which may be numpy scalars) to JSON-native types."""
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    try:
        return value.item()  # numpy scalar
    except AttributeError:
        return str(value)
