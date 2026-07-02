"""Alert correlation (read-time incident grouping) unit tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.models.enums import AlertStatus, Severity
from app.services.correlation_service import correlate_alerts

BASE = datetime(2026, 7, 2, 12, 0, tzinfo=UTC)


def _alert(id, src, pred, sev, mins, status=AlertStatus.NEW, dst="10.0.0.10", prio=None):
    return SimpleNamespace(
        id=id,
        src_ip=src,
        dst_ip=dst,
        prediction=pred,
        severity=sev,
        priority=prio,
        status=status,
        created_at=BASE + timedelta(minutes=mins),
    )


def test_groups_by_source_and_family() -> None:
    alerts = [
        _alert(1, "10.0.0.5", "PortScan", Severity.MEDIUM, 0),
        _alert(2, "10.0.0.5", "PortScan", Severity.HIGH, 5, dst="10.0.0.11"),
        _alert(3, "10.0.0.5", "PortScan", Severity.LOW, 10),
        _alert(4, "10.0.0.9", "DDoS", Severity.CRITICAL, 2),
    ]
    clusters = correlate_alerts(alerts)
    assert len(clusters) == 2
    by_key = {c["correlation_key"]: c for c in clusters}

    ps = by_key["10.0.0.5|PortScan"]
    assert ps["count"] == 3
    assert ps["max_severity"] == "HIGH"  # worst in the group
    assert ps["distinct_destinations"] == 2
    assert set(ps["alert_ids"]) == {1, 2, 3}
    assert ps["activity_span_seconds"] == 600.0  # 0 → 10 min


def test_worst_severity_and_volume_sort_first() -> None:
    alerts = [
        _alert(1, "a", "PortScan", Severity.MEDIUM, 0),
        _alert(2, "a", "PortScan", Severity.MEDIUM, 1),
        _alert(3, "b", "DDoS", Severity.CRITICAL, 0),
    ]
    clusters = correlate_alerts(alerts)
    # CRITICAL DDoS cluster sorts ahead of the larger-but-lower MEDIUM cluster.
    assert clusters[0]["prediction"] == "DDoS"


def test_open_count_excludes_closed() -> None:
    alerts = [
        _alert(1, "a", "DDoS", Severity.HIGH, 0, status=AlertStatus.NEW),
        _alert(2, "a", "DDoS", Severity.HIGH, 1, status=AlertStatus.CLOSED),
    ]
    (cluster,) = correlate_alerts(alerts)
    assert cluster["count"] == 2
    assert cluster["open_count"] == 1


def test_alert_ids_capped() -> None:
    alerts = [_alert(i, "a", "DDoS", Severity.LOW, i) for i in range(100)]
    (cluster,) = correlate_alerts(alerts, max_alert_ids=20)
    assert cluster["count"] == 100
    assert len(cluster["alert_ids"]) == 20
