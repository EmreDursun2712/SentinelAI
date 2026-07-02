"""Alert correlation — collapse repeated alerts into incidents.

A noisy source (a port scan, a DDoS burst) produces dozens of near-identical
alerts. Showing each one buries the signal and fatigues the analyst. This service
groups recent alerts by **(source IP, predicted family)** into *clusters* — one
"incident" per attacker/behaviour — with the count, time span, worst severity,
and the member alert IDs. It's computed at read time (no schema change), so the
grouping stays consistent with whatever alerts currently exist.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Alert
from app.models.enums import AlertStatus

_SEVERITY_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
_CLOSED = {AlertStatus.CLOSED}
DEFAULT_WINDOW_HOURS = 24
MAX_ALERT_IDS = 50


def _sev_value(sev: Any) -> str | None:
    if sev is None:
        return None
    return sev.value if hasattr(sev, "value") else str(sev)


def correlate_alerts(alerts: list[Any], *, max_alert_ids: int = MAX_ALERT_IDS) -> list[dict]:
    """Group ``alerts`` into (src_ip, prediction) clusters, worst/newest first.

    Pure — accepts any objects with ``id/src_ip/dst_ip/prediction/severity/
    priority/status/created_at``. Returns JSON-friendly cluster dicts.
    """
    groups: dict[str, dict[str, Any]] = {}
    for a in alerts:
        key = f"{a.src_ip}|{a.prediction}"
        g = groups.get(key)
        if g is None:
            g = {
                "correlation_key": key,
                "src_ip": str(a.src_ip),
                "prediction": a.prediction,
                "count": 0,
                "open_count": 0,
                "first_seen": a.created_at,
                "last_seen": a.created_at,
                "max_severity": None,
                "_max_sev_rank": 0,
                "max_priority": None,
                "_dst_ips": set(),
                "alert_ids": [],
            }
            groups[key] = g

        g["count"] += 1
        if a.status not in _CLOSED:
            g["open_count"] += 1
        if a.created_at < g["first_seen"]:
            g["first_seen"] = a.created_at
        if a.created_at > g["last_seen"]:
            g["last_seen"] = a.created_at

        sev = _sev_value(a.severity)
        rank = _SEVERITY_RANK.get(sev or "", 0)
        if rank > g["_max_sev_rank"]:
            g["_max_sev_rank"] = rank
            g["max_severity"] = sev
        if a.priority is not None and (g["max_priority"] is None or a.priority > g["max_priority"]):
            g["max_priority"] = float(a.priority)
        if a.dst_ip is not None:
            g["_dst_ips"].add(str(a.dst_ip))
        if len(g["alert_ids"]) < max_alert_ids:
            g["alert_ids"].append(a.id)

    clusters: list[dict[str, Any]] = []
    for g in groups.values():
        span = max((g["last_seen"] - g["first_seen"]).total_seconds(), 0.0)
        clusters.append(
            {
                "correlation_key": g["correlation_key"],
                "src_ip": g["src_ip"],
                "prediction": g["prediction"],
                "count": g["count"],
                "open_count": g["open_count"],
                "first_seen": g["first_seen"],
                "last_seen": g["last_seen"],
                "activity_span_seconds": span,
                "max_severity": g["max_severity"],
                "max_priority": g["max_priority"],
                "distinct_destinations": len(g["_dst_ips"]),
                "alert_ids": g["alert_ids"],
            }
        )

    # Worst first: severity, then how many alerts, then most recent.
    clusters.sort(
        key=lambda c: (
            _SEVERITY_RANK.get(c["max_severity"] or "", 0),
            c["count"],
            c["last_seen"],
        ),
        reverse=True,
    )
    return clusters


async def list_correlated_alerts(
    session: AsyncSession,
    *,
    window_hours: int = DEFAULT_WINDOW_HOURS,
    limit: int = 50,
) -> list[dict]:
    """Fetch recent (non-archived) alerts and return the top correlated clusters."""
    since = datetime.now(UTC) - timedelta(hours=window_hours)
    rows = list(
        (
            await session.execute(
                select(Alert)
                .where(Alert.created_at >= since, Alert.archived_at.is_(None))
                .order_by(desc(Alert.created_at))
            )
        )
        .scalars()
        .all()
    )
    return correlate_alerts(rows)[:limit]
