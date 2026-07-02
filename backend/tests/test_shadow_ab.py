"""Label-aware A/B evaluation + promote recommendation (no DB)."""

from __future__ import annotations

from app.services.model_lifecycle_service import (
    PROMOTE_F1_MARGIN,
    PROMOTE_MIN_LABELED,
    PROMOTE_MIN_SAMPLES,
    build_recommendation,
    evaluate_against_labels,
)


def test_evaluate_against_labels_perfect() -> None:
    preds = ["BENIGN", "DDoS", "PortScan"]
    truth = ["BENIGN", "DDoS", "PortScan"]
    ev = evaluate_against_labels(preds, truth)
    assert ev is not None
    assert ev["accuracy"] == 1.0
    assert ev["macro_f1"] == 1.0
    assert ev["labeled_count"] == 3
    assert set(ev["class_labels"]) == {"BENIGN", "DDoS", "PortScan"}


def test_evaluate_ignores_unlabeled_rows() -> None:
    preds = ["BENIGN", "DDoS", "DDoS"]
    truth = ["BENIGN", None, "DDoS"]  # middle row has no ground truth
    ev = evaluate_against_labels(preds, truth)
    assert ev is not None
    assert ev["labeled_count"] == 2  # only the two labelled rows count


def test_evaluate_returns_none_without_labels() -> None:
    assert evaluate_against_labels(["BENIGN"], [None]) is None


def _eval(macro_f1: float, labeled: int) -> dict:
    return {"macro_f1": macro_f1, "labeled_count": labeled, "accuracy": macro_f1}


def test_recommendation_promotes_on_clear_gain() -> None:
    cand = _eval(0.90, PROMOTE_MIN_LABELED)
    active = _eval(0.90 - PROMOTE_F1_MARGIN - 0.01, PROMOTE_MIN_LABELED)
    rec = build_recommendation(cand, active, sample_count=PROMOTE_MIN_SAMPLES)
    assert rec["decision"] == "promote"
    assert rec["macro_f1_delta"] >= PROMOTE_F1_MARGIN


def test_recommendation_holds_on_small_gain() -> None:
    cand = _eval(0.90, PROMOTE_MIN_LABELED)
    active = _eval(0.895, PROMOTE_MIN_LABELED)  # +0.005 < margin
    rec = build_recommendation(cand, active, sample_count=PROMOTE_MIN_SAMPLES)
    assert rec["decision"] == "hold"


def test_recommendation_holds_on_too_few_samples() -> None:
    cand = _eval(0.99, 5)
    active = _eval(0.10, 5)
    rec = build_recommendation(cand, active, sample_count=PROMOTE_MIN_SAMPLES - 1)
    assert rec["decision"] == "hold"
    assert "labelled" in rec["reason"]


def test_recommendation_insufficient_labels() -> None:
    rec = build_recommendation(None, None, sample_count=100)
    assert rec["decision"] == "insufficient_labels"
    assert rec["macro_f1_delta"] is None
