"""Host timeline — a kill-chain-style view of everything touching one IP.

Given a host/IP, this merges its **flows** (``network_events``), the **alerts** it
raised or was targeted by, and the **response actions** taken on those alerts into
a single time-ordered narrative. Each entry carries a coarse kill-chain *phase*
(Activity → Detection → Triage → Response) so the frontend can draw an attack
timeline the analyst can scan top-to-bottom.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Alert, NetworkEvent, ResponseAction

DEFAULT_WINDOW_HOURS = 24
MAX_EVENTS = 300
MAX_ALERTS = 200

# kind → kill-chain phase label (coarse; illustrative, not full MITRE mapping).
_PHASE = {
    "flow": "Activity",
    "alert": "Detection",
    "triage": "Triage",
    "response": "Response",
}

_SEVERITY_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


def _entry(timestamp: datetime, kind: str, title: str, **extra: Any) -> dict[str, Any]:
    return {
        "timestamp": timestamp,
        "kind": kind,
        "phase": _PHASE.get(kind, "Activity"),
        "title": title,
        **extra,
    }


async def host_timeline(
    session: AsyncSession,
    ip: str,
    *,
    window_hours: int = DEFAULT_WINDOW_HOURS,
) -> dict[str, Any]:
    """Return a merged, newest-first timeline + summary for ``ip``."""
    since = datetime.now(UTC) - timedelta(hours=window_hours)

    events = list(
        (
            await session.execute(
                select(NetworkEvent)
                .where(
                    NetworkEvent.event_time >= since,
                    or_(NetworkEvent.src_ip == ip, NetworkEvent.dst_ip == ip),
                )
                .order_by(desc(NetworkEvent.event_time))
                .limit(MAX_EVENTS)
            )
        )
        .scalars()
        .all()
    )
    alerts = list(
        (
            await session.execute(
                select(Alert)
                .where(
                    Alert.created_at >= since,
                    or_(Alert.src_ip == ip, Alert.dst_ip == ip),
                )
                .order_by(desc(Alert.created_at))
                .limit(MAX_ALERTS)
            )
        )
        .scalars()
        .all()
    )
    alert_ids = [a.id for a in alerts]
    actions: list[ResponseAction] = []
    if alert_ids:
        actions = list(
            (
                await session.execute(
                    select(ResponseAction)
                    .where(ResponseAction.alert_id.in_(alert_ids))
                    .order_by(desc(ResponseAction.created_at))
                )
            )
            .scalars()
            .all()
        )

    items: list[dict[str, Any]] = []
    for e in events:
        direction = "→ from this host" if str(e.src_ip) == ip else "← to this host"
        items.append(
            _entry(
                e.event_time,
                "flow",
                f"Flow {e.src_ip}:{e.src_port or '-'} → {e.dst_ip}:{e.dst_port or '-'} "
                f"({e.protocol or 'proto?'}) {direction}",
                label=e.label,
            )
        )
    for a in alerts:
        sev = a.severity.value if a.severity is not None else None
        items.append(
            _entry(
                a.created_at,
                "alert",
                f"Alert #{a.id}: {a.prediction} (confidence {a.confidence:.2f})",
                severity=sev,
                prediction=a.prediction,
                alert_id=a.id,
            )
        )
        if a.triaged_at is not None:
            prio = f", priority {a.priority:.1f}" if a.priority is not None else ""
            items.append(
                _entry(
                    a.triaged_at,
                    "triage",
                    f"Triaged alert #{a.id}: severity {sev or '—'}{prio}",
                    severity=sev,
                    alert_id=a.id,
                )
            )
    for act in actions:
        ts = act.executed_at or act.created_at
        items.append(
            _entry(
                ts,
                "response",
                f"Response {act.action_type.value} — {act.status.value}",
                alert_id=act.alert_id,
            )
        )

    items.sort(key=lambda x: x["timestamp"], reverse=True)

    # Summary.
    families = sorted({a.prediction for a in alerts})
    max_sev = None
    max_rank = 0
    for a in alerts:
        sev = a.severity.value if a.severity is not None else None
        rank = _SEVERITY_RANK.get(sev or "", 0)
        if rank > max_rank:
            max_rank, max_sev = rank, sev
    all_ts = [it["timestamp"] for it in items]
    summary = {
        "ip": ip,
        "event_count": len(events),
        "alert_count": len(alerts),
        "response_count": len(actions),
        "families": families,
        "max_severity": max_sev,
        "first_seen": min(all_ts) if all_ts else None,
        "last_seen": max(all_ts) if all_ts else None,
    }
    return {"ip": ip, "window_hours": window_hours, "summary": summary, "items": items}
