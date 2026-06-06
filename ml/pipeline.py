"""Build sklearn Pipelines for SentinelAI detection.

The whole transformer+classifier chain is bundled into a single
``sklearn.pipeline.Pipeline`` so the backend can ``joblib.load`` one file and
call ``predict`` / ``predict_proba`` without rebuilding the preprocessor.
"""

from __future__ import annotations

from typing import Literal

from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline

Algorithm = Literal["random_forest", "gradient_boosting"]


def build_pipeline(
    *,
    algorithm: Algorithm = "random_forest",
    random_state: int = 42,
    n_jobs: int = -1,
    n_estimators: int = 200,
) -> Pipeline:
    """Construct an unfit Pipeline for the chosen algorithm."""
    if algorithm == "random_forest":
        clf = RandomForestClassifier(
            n_estimators=n_estimators,
            max_depth=None,
            min_samples_leaf=2,
            class_weight="balanced",
            n_jobs=n_jobs,
            random_state=random_state,
        )
    elif algorithm == "gradient_boosting":
        # GradientBoostingClassifier doesn't support n_jobs; keep it modest.
        clf = GradientBoostingClassifier(
            n_estimators=min(n_estimators, 200),
            max_depth=3,
            random_state=random_state,
        )
    else:
        raise ValueError(f"Unknown algorithm: {algorithm!r}")

    return Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("classifier", clf),
        ]
    )
