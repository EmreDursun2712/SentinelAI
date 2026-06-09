"""DB-free unit tests for the ML-maturity helpers.

Covers feature-coverage assessment + the coverage guardrail, the analyst-feedback
quality proxy, and the shadow-eval comparison math. The DB-bound lifecycle
(activate/rollback, shadow persistence, drift feedback on real rows) is covered in
tests/integration/test_model_lifecycle.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.core.errors import AppError
from app.services.detection_service import assess_feature_coverage, coverage_warn_threshold
from app.services.drift_service import compute_feedback_stats
from app.services.model_lifecycle_service import compare_predictions
from app.services.model_registry import ModelBundle

# ----- feature coverage ----------------------------------------------------


def _bundle(feature_order: list[str], metadata: dict | None = None) -> ModelBundle:
    return ModelBundle(
        pipeline=object(),
        metadata=metadata or {},
        classes=["BENIGN", "DDoS"],
        feature_order=feature_order,
        name="t",
        version="v0",
        algorithm="fake",
        artifact_dir=Path("/tmp/t"),
        loaded_at=datetime.now(UTC),
    )


def test_assess_full_coverage() -> None:
    report = assess_feature_coverage([{"a": 1.0, "b": 2.0, "c": 3.0}], ["a", "b", "c"])
    assert report["coverage"] == 1.0
    assert report["n_present"] == 3
    assert report["missing"] == []


def test_assess_partial_coverage_counts_missing_columns() -> None:
    # Only 'a' is present; 'b' is absent, 'c' is non-finite → both missing.
    report = assess_feature_coverage(
        [{"a": 1.0, "c": float("inf")}, {"a": 2.0}], ["a", "b", "c", "d"]
    )
    assert report["n_expected"] == 4
    assert report["n_present"] == 1
    assert report["coverage"] == 0.25
    assert set(report["missing"]) == {"b", "c", "d"}


def test_assess_present_in_any_row() -> None:
    # 'b' appears (finite) only in the second row — still counts as present.
    report = assess_feature_coverage([{"a": 1.0}, {"a": 2.0, "b": 9.0}], ["a", "b"])
    assert report["coverage"] == 1.0


def test_assess_empty_input_is_full_coverage() -> None:
    assert assess_feature_coverage([], ["a", "b"])["coverage"] == 1.0
    assert assess_feature_coverage([{"a": 1}], [])["coverage"] == 1.0


def test_coverage_warn_threshold_prefers_model_metadata() -> None:
    assert coverage_warn_threshold(_bundle(["a"], {"expected_feature_coverage": 0.9}), 0.5) == 0.9
    # Falls back when the model doesn't declare one.
    assert coverage_warn_threshold(_bundle(["a"], {}), 0.5) == 0.5
    # Bad metadata value → fallback.
    assert coverage_warn_threshold(_bundle(["a"], {"expected_feature_coverage": "x"}), 0.5) == 0.5


def test_enforce_feature_coverage_raises_below_min(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.routers import detection as detection_router

    monkeypatch.setenv("SENTINEL_DETECTION_FEATURE_COVERAGE_MIN", "0.6")
    get_settings.cache_clear()
    try:
        bundle = _bundle(["a", "b", "c", "d"])
        with pytest.raises(AppError):
            detection_router._enforce_feature_coverage(bundle, [{"a": 1.0}])
        # Above the floor → returns the report.
        report = detection_router._enforce_feature_coverage(
            bundle, [{"a": 1, "b": 2, "c": 3, "d": 4}]
        )
        assert report["coverage"] == 1.0
    finally:
        monkeypatch.delenv("SENTINEL_DETECTION_FEATURE_COVERAGE_MIN", raising=False)
        get_settings.cache_clear()


def test_enforce_feature_coverage_disabled_by_default() -> None:
    get_settings.cache_clear()
    from app.api.routers import detection as detection_router

    # Default min is 0 → never raises, even with near-zero coverage.
    report = detection_router._enforce_feature_coverage(_bundle(["a", "b", "c"]), [{"a": 1.0}])
    assert report["coverage"] < 0.5


# ----- analyst-feedback quality proxy --------------------------------------


def test_feedback_stats_rates_and_quality() -> None:
    dispositions = [
        "CONFIRMED",
        "CONFIRMED",
        "CONFIRMED",
        "FALSE_POSITIVE",
        "OPEN",
        "UNDER_REVIEW",
    ]
    stats = compute_feedback_stats(dispositions)
    assert stats["total"] == 6
    assert stats["confirmed_rate"] == pytest.approx(0.5)
    assert stats["false_positive_rate"] == pytest.approx(1 / 6, abs=1e-3)
    assert stats["unresolved_rate"] == pytest.approx(1 / 3, abs=1e-3)
    assert stats["verdict_count"] == 4
    # quality = CONFIRMED / (CONFIRMED + FALSE_POSITIVE) = 3/4
    assert stats["quality_score"] == pytest.approx(0.75)


def test_feedback_stats_empty() -> None:
    stats = compute_feedback_stats([])
    assert stats["total"] == 0
    assert stats["quality_score"] is None
    assert stats["false_positive_rate"] == 0.0


def test_feedback_stats_no_verdicts_quality_none() -> None:
    stats = compute_feedback_stats(["OPEN", "OPEN", "UNDER_REVIEW"])
    assert stats["quality_score"] is None
    assert stats["unresolved_rate"] == pytest.approx(1.0)


# ----- shadow-eval comparison ----------------------------------------------


def test_compare_predictions_agreement_and_deltas() -> None:
    metrics = compare_predictions(
        candidate_labels=["DDoS", "BENIGN", "DDoS", "PortScan"],
        candidate_confs=[0.9, 0.8, 0.7, 0.6],
        active_labels=["DDoS", "BENIGN", "BENIGN", "PortScan"],
        active_confs=[0.8, 0.85, 0.6, 0.55],
    )
    assert metrics["sample_count"] == 4
    assert metrics["agreement_rate"] == pytest.approx(0.75)
    assert metrics["disagreements"] == 1
    assert metrics["candidate_label_distribution"]["DDoS"] == pytest.approx(0.5)
    assert metrics["mean_confidence_delta"] is not None


def test_compare_predictions_empty() -> None:
    metrics = compare_predictions([], [], [], [])
    assert metrics["sample_count"] == 0
    assert metrics["agreement_rate"] is None
