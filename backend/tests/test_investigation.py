"""Investigation pure-builder tests — no DB needed."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.models.enums import AlertStatus, Severity
from app.services.investigation_service import (
    _build_summary,
    _build_timeline,
    _compute_statistics,
    _format_duration,
)

# ---------- _format_duration -----------------------------------------------


@pytest.mark.parametrize(
    ("seconds", "expected_substr"),
    [
        (0.25, "ms"),
        (1.5, "s"),
        (90.0, "min"),
        (3700.0, "h"),
        (172800.0, "d"),
    ],
)
def test_format_duration_picks_correct_unit(seconds: float, expected_substr: str) -> None:
    assert expected_substr in _format_duration(seconds)


# ---------- helpers --------------------------------------------------------


def _alert(**overrides):
    base = dict(
        id=42,
        src_ip="203.0.113.7",
        dst_ip="10.0.0.10",
        src_port=38821,
        dst_port=22,
        protocol="TCP",
        prediction="BruteForce",
        confidence=0.92,
        severity=Severity.HIGH,
        priority=67.0,
        status=AlertStatus.TRIAGED,
        created_at=datetime(2026, 5, 21, 8, 25, 42, tzinfo=UTC),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _event(**overrides):
    base = dict(
        id=100,
        event_time=datetime(2026, 5, 21, 8, 25, 42, tzinfo=UTC),
        src_ip="203.0.113.7",
        dst_ip="10.0.0.10",
        src_port=38821,
        dst_port=22,
        protocol="TCP",
        label="BruteForce",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _other_alert(**overrides):
    base = dict(
        id=41,
        src_ip="203.0.113.7",
        dst_ip="10.0.0.10",
        src_port=38800,
        dst_port=22,
        protocol="TCP",
        prediction="BruteForce",
        severity=Severity.HIGH,
        priority=65.0,
        confidence=0.91,
        created_at=datetime(2026, 5, 21, 8, 24, 0, tzinfo=UTC),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------- _compute_statistics --------------------------------------------


def test_statistics_count_related_events_and_alerts() -> None:
    alert = _alert()
    events = [
        _event(id=1, event_time=alert.created_at - timedelta(seconds=10)),
        _event(id=2, event_time=alert.created_at + timedelta(seconds=5)),
    ]
    alerts = [
        _other_alert(id=10, src_ip=alert.src_ip),
        _other_alert(id=11, src_ip="198.51.100.99", dst_ip=alert.dst_ip),
    ]
    stats = _compute_statistics(alert, events, alerts)
    assert stats.related_event_count == 2
    assert stats.related_alert_count == 2
    assert stats.same_src_ip_alert_count == 1
    assert stats.same_dst_ip_alert_count == 2  # both share dst_ip with alert
    assert stats.same_family_alert_count == 2  # both predict BruteForce


def test_statistics_distinct_ip_counts() -> None:
    alert = _alert()
    events = [
        _event(src_ip="A", dst_ip="X"),
        _event(src_ip="A", dst_ip="Y"),
        _event(src_ip="B", dst_ip="X"),
    ]
    stats = _compute_statistics(alert, events, [])
    assert stats.distinct_source_ips == 2
    assert stats.distinct_destination_ips == 2


def test_statistics_activity_span() -> None:
    alert = _alert()
    t0 = alert.created_at
    events = [
        _event(event_time=t0),
        _event(event_time=t0 + timedelta(minutes=8)),
    ]
    stats = _compute_statistics(alert, events, [])
    assert stats.first_seen == t0
    assert stats.last_seen == t0 + timedelta(minutes=8)
    assert stats.activity_span_seconds == pytest.approx(480.0)


def test_statistics_empty_events() -> None:
    stats = _compute_statistics(_alert(), [], [])
    assert stats.related_event_count == 0
    assert stats.distinct_source_ips == 0
    assert stats.first_seen is None
    assert stats.last_seen is None
    assert stats.activity_span_seconds is None
    assert stats.top_label is None
    assert stats.top_prediction is None


def test_statistics_top_label_and_prediction() -> None:
    alert = _alert()
    events = [
        _event(label="DDoS"),
        _event(label="DDoS"),
        _event(label="BruteForce"),
    ]
    alerts = [
        _other_alert(prediction="DDoS"),
        _other_alert(prediction="DDoS"),
        _other_alert(prediction="BruteForce"),
    ]
    stats = _compute_statistics(alert, events, alerts)
    assert stats.top_label == "DDoS"
    assert stats.top_prediction == "DDoS"


# ---------- _build_timeline ------------------------------------------------


def test_timeline_is_sorted_and_anchored_by_current_alert() -> None:
    alert = _alert()
    events = [
        _event(id=1, event_time=alert.created_at - timedelta(seconds=10)),
        _event(id=2, event_time=alert.created_at + timedelta(seconds=20)),
    ]
    alerts = [_other_alert(id=10, created_at=alert.created_at - timedelta(minutes=1))]
    items = _build_timeline(alert, events, alerts)

    timestamps = [i.timestamp for i in items]
    assert timestamps == sorted(timestamps)
    current = [i for i in items if i.is_current_alert]
    assert len(current) == 1
    assert current[0].alert_id == alert.id


def test_timeline_event_summary_contains_endpoints() -> None:
    alert = _alert()
    items = _build_timeline(alert, [_event(src_port=1234, dst_port=22)], [])
    event_items = [i for i in items if i.kind == "event"]
    assert event_items
    assert "1234" in event_items[0].summary
    assert ":22" in event_items[0].summary


def test_timeline_alert_summary_uses_severity_or_unrated() -> None:
    alert = _alert()
    rated = _other_alert(severity=Severity.CRITICAL)
    unrated = _other_alert(severity=None, id=99)
    items = _build_timeline(alert, [], [rated, unrated])
    alert_items = [i for i in items if i.kind == "alert" and not i.is_current_alert]
    assert any("CRITICAL" in i.summary for i in alert_items)
    assert any("unrated" in i.summary for i in alert_items)


# ---------- _build_summary -------------------------------------------------


def test_summary_text_mentions_alert_and_counts() -> None:
    alert = _alert()
    stats = _compute_statistics(
        alert,
        [_event()],
        [_other_alert()],
    )
    summary, bullets = _build_summary(alert, stats)
    assert "#42" in summary
    assert "BruteForce" in summary
    assert "203.0.113.7" in summary
    assert "10.0.0.10:22" in summary
    assert "1 related alert" in summary or "1 related alert(s)" in summary
    assert any("203.0.113.7" in b for b in bullets)


def test_summary_flags_distributed_activity() -> None:
    alert = _alert()
    events = [_event(src_ip="A"), _event(src_ip="B"), _event(src_ip="C")]
    stats = _compute_statistics(alert, events, [])
    _, bullets = _build_summary(alert, stats)
    assert any("distinct source IPs" in b for b in bullets)


def test_summary_flags_probing_pattern() -> None:
    alert = _alert()
    events = [
        _event(dst_ip="10.0.0.10"),
        _event(dst_ip="10.0.0.11"),
        _event(dst_ip="10.0.0.12"),
    ]
    stats = _compute_statistics(alert, events, [])
    _, bullets = _build_summary(alert, stats)
    assert any("probing multiple hosts" in b for b in bullets)


def test_summary_flags_label_vs_prediction_mismatch() -> None:
    alert = _alert(prediction="DDoS")
    events = [_event(label="BruteForce"), _event(label="BruteForce")]
    stats = _compute_statistics(alert, events, [])
    _, bullets = _build_summary(alert, stats)
    assert any("possible mismatch" in b for b in bullets)


def test_summary_says_first_observation_when_no_history() -> None:
    alert = _alert()
    stats = _compute_statistics(alert, [], [])
    _, bullets = _build_summary(alert, stats)
    assert any("first observation" in b for b in bullets)


def test_summary_handles_unrated_alert_gracefully() -> None:
    alert = _alert(severity=None, priority=None)
    stats = _compute_statistics(alert, [], [])
    summary, _ = _build_summary(alert, stats)
    assert "severity=unrated" in summary
    assert "priority=—" in summary


def test_summary_is_deterministic() -> None:
    alert = _alert()
    events = [_event(id=1), _event(id=2)]
    alerts = [_other_alert(id=10)]
    stats = _compute_statistics(alert, events, alerts)
    s1, b1 = _build_summary(alert, stats)
    s2, b2 = _build_summary(alert, stats)
    assert s1 == s2
    assert b1 == b2
