"""Detection service unit tests — no DB required."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from app.services.detection_service import (
    Prediction,
    build_feature_matrix,
    predict_flows,
    should_create_alert,
)
from app.services.model_registry import ModelBundle, ModelRegistry


# ----- build_feature_matrix ------------------------------------------------


def test_build_feature_matrix_aligns_to_feature_order() -> None:
    feature_order = ["a", "b", "c"]
    df = build_feature_matrix(
        [
            {"a": 1.0, "b": 2.0, "c": 3.0},
            {"a": 4.0, "c": 6.0},  # b missing
            {},  # everything missing
        ],
        feature_order,
    )
    assert list(df.columns) == feature_order
    assert df.iloc[0].tolist() == [1.0, 2.0, 3.0]
    assert df.iloc[1, 0] == 4.0
    assert np.isnan(df.iloc[1, 1])
    assert df.iloc[1, 2] == 6.0
    assert df.iloc[2].isna().all()


def test_build_feature_matrix_drops_inf_and_strings_to_nan() -> None:
    df = build_feature_matrix(
        [{"a": float("inf"), "b": "not-a-number", "c": None}],
        ["a", "b", "c"],
    )
    assert df.iloc[0].isna().all()


def test_build_feature_matrix_empty_input() -> None:
    df = build_feature_matrix([], ["a", "b"])
    assert list(df.columns) == ["a", "b"]
    assert len(df) == 0


# ----- should_create_alert -------------------------------------------------


def test_alert_decision_below_threshold_does_not_trigger() -> None:
    assert not should_create_alert(
        "DDoS", confidence=0.4, threshold=0.5, benign_label="BENIGN"
    )


def test_alert_decision_at_threshold_triggers() -> None:
    assert should_create_alert(
        "DDoS", confidence=0.5, threshold=0.5, benign_label="BENIGN"
    )


def test_alert_decision_benign_never_triggers() -> None:
    assert not should_create_alert(
        "BENIGN", confidence=1.0, threshold=0.0, benign_label="BENIGN"
    )


def test_alert_decision_non_benign_above_threshold_triggers() -> None:
    assert should_create_alert(
        "PortScan", confidence=0.99, threshold=0.5, benign_label="BENIGN"
    )


# ----- predict_flows (with a fake pipeline) --------------------------------


class _FakePipeline:
    """Stand-in for a fitted sklearn Pipeline."""

    def __init__(self, classes: list[str], rows: list[list[float]]) -> None:
        self.classes_ = classes
        self._rows = rows

    def predict_proba(self, X) -> np.ndarray:  # noqa: ARG002 — interface only
        return np.array(self._rows)


def _make_bundle(classes: list[str], probabilities_per_row: list[list[float]]) -> ModelBundle:
    from datetime import UTC, datetime

    return ModelBundle(
        pipeline=_FakePipeline(classes, probabilities_per_row),
        metadata={"name": "test", "version": "v0", "algorithm": "fake"},
        classes=classes,
        feature_order=["flow_duration", "total_fwd_packets"],
        name="test",
        version="v0",
        algorithm="fake",
        artifact_dir=Path("/tmp/test"),
        loaded_at=datetime.now(UTC),
    )


def test_predict_flows_returns_top_class_with_probabilities() -> None:
    bundle = _make_bundle(
        classes=["BENIGN", "DDoS"],
        probabilities_per_row=[[0.1, 0.9], [0.8, 0.2]],
    )
    flows = [
        SimpleNamespace(features={"flow_duration": 50.0, "total_fwd_packets": 4}),
        SimpleNamespace(features={"flow_duration": 1500.0, "total_fwd_packets": 12}),
    ]
    preds = predict_flows(
        bundle, flows, threshold=0.5, benign_label="BENIGN"  # type: ignore[arg-type]
    )
    assert len(preds) == 2

    assert preds[0].predicted_label == "DDoS"
    assert preds[0].confidence == pytest.approx(0.9)
    assert preds[0].class_probabilities == {"BENIGN": 0.1, "DDoS": 0.9}
    assert preds[0].benign is False
    # predict_flows never persists, so alert_created stays False
    assert preds[0].alert_created is False
    assert preds[0].alert_id is None

    assert preds[1].predicted_label == "BENIGN"
    assert preds[1].benign is True
    assert preds[1].alert_created is False


def test_predict_flows_empty_input_returns_empty_list() -> None:
    bundle = _make_bundle(classes=["BENIGN"], probabilities_per_row=[])
    assert predict_flows(bundle, [], threshold=0.5, benign_label="BENIGN") == []


# ----- ModelRegistry: gracefully handles missing artifacts -----------------


def test_model_registry_returns_none_when_artifacts_missing(tmp_path: Path) -> None:
    reg = ModelRegistry()
    # Empty dir — no latest/, no model.joblib, no metadata.json
    assert reg.load_from_disk(tmp_path) is None
    assert reg.get() is None
    assert reg.is_loaded() is False


def test_model_registry_rejects_metadata_without_classes(tmp_path: Path) -> None:
    latest = tmp_path / "latest"
    latest.mkdir()
    # A "model.joblib" file just needs to exist for the early file check;
    # we won't actually load it because metadata is invalid first... wait,
    # registry loads model THEN metadata. So write a tiny pickle.
    import joblib
    joblib.dump({"fake": "model"}, latest / "model.joblib")
    (latest / "metadata.json").write_text(json.dumps({"classes": [], "feature_order": []}))

    reg = ModelRegistry()
    assert reg.load_from_disk(tmp_path) is None
    assert not reg.is_loaded()
