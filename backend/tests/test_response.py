"""Response rule-engine tests — pure functions, no DB."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.models.enums import (
    AlertDisposition,
    AlertStatus,
    ResponseActionType,
    Severity,
)
from app.services.response_rules import (
    LOW_CONFIDENCE_SUPPRESS_THRESHOLD,
    Recommendation,
    recommend_actions,
)


def _alert(
    *,
    severity: Severity | None = None,
    prediction: str = "DDoS",
    confidence: float = 0.9,
    src_ip: str = "203.0.113.7",
    dst_ip: str = "10.0.0.10",
    dst_port: int | None = 443,
    status: AlertStatus = AlertStatus.TRIAGED,
    disposition: AlertDisposition = AlertDisposition.OPEN,
    alert_id: int = 1,
) -> SimpleNamespace:
    """Build a fake Alert-shaped object so the rule engine sees real attribute access."""
    return SimpleNamespace(
        id=alert_id,
        severity=severity,
        prediction=prediction,
        confidence=confidence,
        src_ip=src_ip,
        dst_ip=dst_ip,
        dst_port=dst_port,
        status=status,
        disposition=disposition,
    )


# ---------- closed / terminal early returns --------------------------------


def test_closed_alert_returns_no_recommendations() -> None:
    alert = _alert(severity=Severity.HIGH, status=AlertStatus.CLOSED)
    assert recommend_actions(alert) == []


def test_already_false_positive_returns_only_notify() -> None:
    alert = _alert(
        severity=Severity.HIGH,
        disposition=AlertDisposition.FALSE_POSITIVE,
    )
    recs = recommend_actions(alert)
    assert len(recs) == 1
    assert recs[0].action_type == ResponseActionType.NOTIFY_ANALYST


# ---------- CRITICAL severity ----------------------------------------------


def test_critical_generates_block_ticket_notify() -> None:
    alert = _alert(severity=Severity.CRITICAL, prediction="DDoS", confidence=0.95)
    types = [r.action_type for r in recommend_actions(alert)]
    assert ResponseActionType.BLOCK_IP in types
    assert ResponseActionType.CREATE_TICKET in types
    assert ResponseActionType.NOTIFY_ANALYST in types


def test_critical_block_auto_executes() -> None:
    alert = _alert(severity=Severity.CRITICAL, prediction="DDoS")
    block = next(
        r for r in recommend_actions(alert) if r.action_type == ResponseActionType.BLOCK_IP
    )
    assert block.auto_execute is True
    assert block.payload["target_ip"] == alert.src_ip
    assert block.payload["duration"] == "24h"


def test_critical_brute_force_adds_isolate_host() -> None:
    alert = _alert(
        severity=Severity.CRITICAL, prediction="BruteForce", dst_port=22, dst_ip="10.0.0.10"
    )
    types = [r.action_type for r in recommend_actions(alert)]
    assert ResponseActionType.ISOLATE_HOST in types


def test_critical_infiltration_adds_isolate_host() -> None:
    alert = _alert(severity=Severity.CRITICAL, prediction="Infiltration")
    types = [r.action_type for r in recommend_actions(alert)]
    assert ResponseActionType.ISOLATE_HOST in types


def test_critical_ddos_adds_rate_limit() -> None:
    alert = _alert(severity=Severity.CRITICAL, prediction="DDoS")
    types = [r.action_type for r in recommend_actions(alert)]
    assert ResponseActionType.RATE_LIMIT in types


# ---------- HIGH severity --------------------------------------------------


def test_high_generates_block_ticket_notify() -> None:
    alert = _alert(severity=Severity.HIGH, prediction="BruteForce", confidence=0.85)
    types = [r.action_type for r in recommend_actions(alert)]
    assert ResponseActionType.BLOCK_IP in types
    assert ResponseActionType.CREATE_TICKET in types
    assert ResponseActionType.NOTIFY_ANALYST in types


def test_high_block_auto_executes_with_shorter_duration() -> None:
    alert = _alert(severity=Severity.HIGH, prediction="BruteForce")
    block = next(
        r for r in recommend_actions(alert) if r.action_type == ResponseActionType.BLOCK_IP
    )
    assert block.auto_execute is True
    assert block.payload["duration"] == "6h"


def test_high_ddos_adds_rate_limit() -> None:
    alert = _alert(severity=Severity.HIGH, prediction="DDoS")
    types = [r.action_type for r in recommend_actions(alert)]
    assert ResponseActionType.RATE_LIMIT in types


# ---------- MEDIUM severity ------------------------------------------------


def test_medium_recommends_block_pending_approval() -> None:
    alert = _alert(severity=Severity.MEDIUM, prediction="PortScan", confidence=0.7)
    recs = recommend_actions(alert)
    block = next((r for r in recs if r.action_type == ResponseActionType.BLOCK_IP), None)
    assert block is not None
    assert block.auto_execute is False


def test_medium_includes_escalate() -> None:
    alert = _alert(severity=Severity.MEDIUM, prediction="PortScan")
    types = [r.action_type for r in recommend_actions(alert)]
    assert ResponseActionType.ESCALATE in types


# ---------- LOW + low confidence -------------------------------------------


def test_low_low_confidence_suggests_suppress() -> None:
    alert = _alert(
        severity=Severity.LOW,
        prediction="PortScan",
        confidence=LOW_CONFIDENCE_SUPPRESS_THRESHOLD - 0.01,
    )
    types = [r.action_type for r in recommend_actions(alert)]
    assert ResponseActionType.SUPPRESS_ALERT in types


def test_low_high_confidence_just_notifies() -> None:
    alert = _alert(severity=Severity.LOW, prediction="PortScan", confidence=0.85)
    types = [r.action_type for r in recommend_actions(alert)]
    assert ResponseActionType.SUPPRESS_ALERT not in types
    assert ResponseActionType.NOTIFY_ANALYST in types


def test_suppress_requires_approval() -> None:
    alert = _alert(severity=Severity.LOW, prediction="PortScan", confidence=0.3)
    suppress = next(
        r for r in recommend_actions(alert)
        if r.action_type == ResponseActionType.SUPPRESS_ALERT
    )
    # Disposition-changing action — always behind analyst sign-off.
    assert suppress.auto_execute is False


# ---------- BENIGN-classified -----------------------------------------------


def test_benign_predicted_suggests_suppress_regardless_of_severity() -> None:
    alert = _alert(severity=Severity.MEDIUM, prediction="BENIGN", confidence=0.92)
    types = [r.action_type for r in recommend_actions(alert)]
    assert ResponseActionType.SUPPRESS_ALERT in types
    assert ResponseActionType.NOTIFY_ANALYST in types


# ---------- Always-on guarantees -------------------------------------------


def test_every_recommendation_has_non_empty_rationale() -> None:
    for severity in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW):
        for family in ("DDoS", "BruteForce", "PortScan", "Infiltration"):
            alert = _alert(severity=severity, prediction=family, confidence=0.8)
            for rec in recommend_actions(alert):
                assert rec.rationale and len(rec.rationale) > 0


def test_notify_is_always_present_for_active_alerts() -> None:
    for severity in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW):
        alert = _alert(severity=severity, prediction="DDoS")
        types = [r.action_type for r in recommend_actions(alert)]
        assert ResponseActionType.NOTIFY_ANALYST in types, severity


def test_recommendation_payload_contains_target_ip_for_network_actions() -> None:
    alert = _alert(severity=Severity.CRITICAL, prediction="DDoS")
    for rec in recommend_actions(alert):
        if rec.action_type in (
            ResponseActionType.BLOCK_IP,
            ResponseActionType.RATE_LIMIT,
        ):
            assert "target_ip" in rec.payload
        if rec.action_type == ResponseActionType.ISOLATE_HOST:
            assert "target_ip" in rec.payload


def test_recommendation_is_immutable() -> None:
    rec = Recommendation(
        action_type=ResponseActionType.BLOCK_IP,
        auto_execute=True,
        rationale="test",
    )
    with pytest.raises(Exception):
        rec.auto_execute = False  # type: ignore[misc] — frozen dataclass
