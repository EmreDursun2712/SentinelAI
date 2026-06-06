"""Investigation Agent.

Gathers evidence from ``network_events`` and ``alerts`` around the target
alert, builds a deterministic summary, and stores the result as an
``alert_artifacts`` row with ``kind=INVESTIGATION_PACKET``. The Reporting
agent (Phase 6 next) reads from there.

Design choices:

* The retrieval is plain SQL — every claim in the summary maps to a counted
  row, so the analyst can cross-check every line.
* The summary is built by ``_build_summary`` from the gathered evidence;
  there is no free-text generation, no model-side hallucination risk.
* Feature importance, when available, comes from the loaded RandomForest
  pipeline's ``feature_importances_`` — global importance, not per-prediction.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models import AgentDecision, Alert, AlertArtifact, NetworkEvent
from app.models.enums import AgentName, AlertStatus, ArtifactKind
from app.schemas.investigation import (
    FeatureImportanceItem,
    InvestigationPacket,
    InvestigationStatistics,
    RelatedAlertOut,
    RelatedEventOut,
    TimelineItem,
)
from app.services.model_registry import get_model_registry

logger = get_logger(__name__)


DEFAULT_EVENTS_WINDOW_MINUTES = 60
DEFAULT_ALERTS_WINDOW_HOURS = 24
DEFAULT_MAX_EVENTS = 200
DEFAULT_MAX_ALERTS = 50
DEFAULT_TOP_FEATURES = 15


# ---------------------------------------------------------------------------
# Public entry point.
# ---------------------------------------------------------------------------


async def investigate_alert(
    session: AsyncSession,
    alert: Alert,
    *,
    events_window_minutes: int = DEFAULT_EVENTS_WINDOW_MINUTES,
    alerts_window_hours: int = DEFAULT_ALERTS_WINDOW_HOURS,
    max_events: int = DEFAULT_MAX_EVENTS,
    max_alerts: int = DEFAULT_MAX_ALERTS,
    commit: bool = True,
) -> tuple[AlertArtifact, InvestigationPacket]:
    """Gather evidence, persist an ``INVESTIGATION_PACKET`` artifact, return both."""
    related_events, events_truncated = await _fetch_related_events(
        session, alert, window_minutes=events_window_minutes, limit=max_events
    )
    related_alerts, alerts_truncated = await _fetch_related_alerts(
        session, alert, window_hours=alerts_window_hours, limit=max_alerts
    )

    stats = _compute_statistics(alert, related_events, related_alerts)
    timeline = _build_timeline(alert, related_events, related_alerts)
    summary, bullets = _build_summary(alert, stats)
    importance, model_name, model_version = _feature_importance(top_k=DEFAULT_TOP_FEATURES)

    packet = InvestigationPacket(
        alert_id=alert.id,
        generated_at=datetime.now(UTC),
        events_window_minutes=events_window_minutes,
        alerts_window_hours=alerts_window_hours,
        summary=summary,
        summary_bullets=bullets,
        statistics=stats,
        related_alerts=[_to_related_alert(a) for a in related_alerts],
        related_events=[_to_related_event(e) for e in related_events],
        timeline=timeline,
        feature_importance=importance,
        model_name=model_name,
        model_version=model_version,
        truncated=events_truncated or alerts_truncated,
    )

    # JSONB-safe serialization (datetimes → ISO strings, enums → values).
    data: dict[str, Any] = packet.model_dump(mode="json")

    artifact = AlertArtifact(
        alert_id=alert.id,
        kind=ArtifactKind.INVESTIGATION_PACKET,
        data=data,
    )
    session.add(artifact)
    await session.flush()

    # Alert workflow transition.
    alert.investigated_at = datetime.now(UTC)
    if alert.status in {
        AlertStatus.NEW,
        AlertStatus.TRIAGED,
        AlertStatus.AUTO_RESPONDED,
        AlertStatus.AWAITING_ANALYST,
    }:
        alert.status = AlertStatus.INVESTIGATED

    decision = AgentDecision(
        alert_id=alert.id,
        agent=AgentName.INVESTIGATION,
        decision={
            "artifact_id": artifact.id,
            "summary": summary,
            "n_related_events": stats.related_event_count,
            "n_related_alerts": stats.related_alert_count,
            "truncated": packet.truncated,
        },
        reasoning={
            "events_window_minutes": events_window_minutes,
            "alerts_window_hours": alerts_window_hours,
            "max_events": max_events,
            "max_alerts": max_alerts,
            "bullets": bullets,
        },
    )
    session.add(decision)

    if commit:
        await session.commit()
        await session.refresh(artifact)
        await session.refresh(alert)

    logger.info(
        "investigation.completed",
        alert_id=alert.id,
        artifact_id=artifact.id,
        n_events=stats.related_event_count,
        n_alerts=stats.related_alert_count,
        truncated=packet.truncated,
    )
    return artifact, packet


async def get_latest_investigation(
    session: AsyncSession, alert_id: int
) -> AlertArtifact | None:
    """Return the most recent ``INVESTIGATION_PACKET`` artifact for an alert."""
    stmt = (
        select(AlertArtifact)
        .where(
            AlertArtifact.alert_id == alert_id,
            AlertArtifact.kind == ArtifactKind.INVESTIGATION_PACKET,
        )
        .order_by(desc(AlertArtifact.created_at))
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Evidence retrieval.
# ---------------------------------------------------------------------------


async def _fetch_related_events(
    session: AsyncSession,
    alert: Alert,
    *,
    window_minutes: int,
    limit: int,
) -> tuple[list[NetworkEvent], bool]:
    """Events with src_ip OR dst_ip OR label matching the alert, in ±window_minutes."""
    pivot = alert.created_at or datetime.now(UTC)
    since = pivot - timedelta(minutes=window_minutes)
    until = pivot + timedelta(minutes=window_minutes)

    conditions = [
        NetworkEvent.src_ip == alert.src_ip,
        NetworkEvent.dst_ip == alert.dst_ip,
    ]
    if alert.prediction:
        conditions.append(NetworkEvent.label == alert.prediction)

    # Fetch one extra row to detect truncation cheaply.
    stmt = (
        select(NetworkEvent)
        .where(
            NetworkEvent.event_time >= since,
            NetworkEvent.event_time <= until,
            or_(*conditions),
        )
        .order_by(NetworkEvent.event_time.asc())
        .limit(limit + 1)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    truncated = len(rows) > limit
    return rows[:limit], truncated


async def _fetch_related_alerts(
    session: AsyncSession,
    alert: Alert,
    *,
    window_hours: int,
    limit: int,
) -> tuple[list[Alert], bool]:
    """Other alerts in last ``window_hours`` matching src_ip OR dst_ip OR prediction."""
    pivot = alert.created_at or datetime.now(UTC)
    since = pivot - timedelta(hours=window_hours)

    conditions = [
        Alert.src_ip == alert.src_ip,
        Alert.dst_ip == alert.dst_ip,
    ]
    if alert.prediction:
        conditions.append(Alert.prediction == alert.prediction)

    stmt = (
        select(Alert)
        .where(
            Alert.id != alert.id,
            Alert.created_at >= since,
            or_(*conditions),
        )
        .order_by(Alert.created_at.desc())
        .limit(limit + 1)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    truncated = len(rows) > limit
    return rows[:limit], truncated


# ---------------------------------------------------------------------------
# Pure builders (unit-testable in isolation).
# ---------------------------------------------------------------------------


def _compute_statistics(
    alert: Alert, events: list[NetworkEvent], alerts: list[Alert]
) -> InvestigationStatistics:
    first_seen = min((e.event_time for e in events), default=None)
    last_seen = max((e.event_time for e in events), default=None)
    span_seconds: float | None = None
    if first_seen and last_seen:
        span_seconds = max((last_seen - first_seen).total_seconds(), 0.0)

    labels = [e.label for e in events if e.label]
    predictions = [a.prediction for a in alerts if a.prediction]

    return InvestigationStatistics(
        related_event_count=len(events),
        related_alert_count=len(alerts),
        distinct_source_ips=len({e.src_ip for e in events if e.src_ip}),
        distinct_destination_ips=len({e.dst_ip for e in events if e.dst_ip}),
        same_src_ip_alert_count=sum(1 for a in alerts if a.src_ip == alert.src_ip),
        same_dst_ip_alert_count=sum(1 for a in alerts if a.dst_ip == alert.dst_ip),
        same_family_alert_count=sum(
            1 for a in alerts if alert.prediction and a.prediction == alert.prediction
        ),
        first_seen=first_seen,
        last_seen=last_seen,
        activity_span_seconds=span_seconds,
        top_label=Counter(labels).most_common(1)[0][0] if labels else None,
        top_prediction=Counter(predictions).most_common(1)[0][0] if predictions else None,
    )


def _build_timeline(
    alert: Alert, events: list[NetworkEvent], alerts: list[Alert]
) -> list[TimelineItem]:
    items: list[TimelineItem] = []
    for ev in events:
        items.append(
            TimelineItem(
                timestamp=ev.event_time,
                kind="event",
                summary=(
                    f"Flow {ev.src_ip}:{ev.src_port or '-'} → "
                    f"{ev.dst_ip}:{ev.dst_port or '-'} "
                    f"({ev.protocol or 'unknown'}) "
                    f"label={ev.label or 'unlabeled'}"
                ),
                src_ip=ev.src_ip,
                dst_ip=ev.dst_ip,
                label=ev.label,
            )
        )
    for a in alerts:
        sev = a.severity.value if a.severity is not None else "unrated"
        items.append(
            TimelineItem(
                timestamp=a.created_at,
                kind="alert",
                summary=f"Alert #{a.id} {a.prediction} ({sev}) from {a.src_ip}",
                src_ip=a.src_ip,
                dst_ip=a.dst_ip,
                prediction=a.prediction,
                severity=a.severity,
                alert_id=a.id,
            )
        )
    # The current alert itself — anchor of the timeline.
    items.append(
        TimelineItem(
            timestamp=alert.created_at,
            kind="alert",
            summary=(
                f"▶ This alert: #{alert.id} {alert.prediction} "
                f"from {alert.src_ip} to {alert.dst_ip}:{alert.dst_port or '-'}"
            ),
            src_ip=alert.src_ip,
            dst_ip=alert.dst_ip,
            prediction=alert.prediction,
            severity=alert.severity,
            alert_id=alert.id,
            is_current_alert=True,
        )
    )

    items.sort(key=lambda x: x.timestamp)
    return items


def _build_summary(alert: Alert, stats: InvestigationStatistics) -> tuple[str, list[str]]:
    sev = alert.severity.value if alert.severity is not None else "unrated"
    pri = f"{alert.priority:.1f}" if alert.priority is not None else "—"
    dst_label = f"{alert.dst_ip}:{alert.dst_port}" if alert.dst_port else alert.dst_ip

    summary = (
        f"Investigated alert #{alert.id}: {alert.prediction} from {alert.src_ip} "
        f"to {dst_label} (severity={sev}, priority={pri}, confidence={alert.confidence:.2f}). "
        f"Examined {stats.related_alert_count} related alert(s) and "
        f"{stats.related_event_count} related flow(s)."
    )

    bullets: list[str] = []

    # Source activity.
    if stats.same_src_ip_alert_count > 0:
        bullets.append(
            f"Source {alert.src_ip} has {stats.same_src_ip_alert_count} other recent "
            f"alert(s) in the lookback window."
        )
    else:
        bullets.append(
            f"Source {alert.src_ip} has no other recent alerts — likely first observation."
        )

    # Target context.
    if stats.same_dst_ip_alert_count > 0:
        bullets.append(
            f"Target {alert.dst_ip} has {stats.same_dst_ip_alert_count} other recent "
            f"alert(s) — multiple attempts against the same host."
        )

    # Family consistency.
    if stats.same_family_alert_count > 0:
        bullets.append(
            f"{stats.same_family_alert_count} other recent alert(s) share the same "
            f"prediction '{alert.prediction}' — consistent campaign pattern."
        )
    elif stats.top_prediction and stats.top_prediction != alert.prediction:
        bullets.append(
            f"Surrounding alerts mostly predict '{stats.top_prediction}', "
            f"differing from this alert ({alert.prediction})."
        )

    # Time span.
    if stats.activity_span_seconds is not None and stats.first_seen and stats.last_seen:
        bullets.append(
            f"Related flow activity spans {_format_duration(stats.activity_span_seconds)} "
            f"({stats.first_seen.strftime('%Y-%m-%d %H:%M:%S')} → "
            f"{stats.last_seen.strftime('%Y-%m-%d %H:%M:%S')} UTC)."
        )

    # Fan-out / fan-in.
    if stats.distinct_source_ips > 1:
        bullets.append(
            f"{stats.distinct_source_ips} distinct source IPs touched this scope — "
            f"possible distributed activity."
        )
    if stats.distinct_destination_ips > 1:
        bullets.append(
            f"{stats.distinct_destination_ips} distinct destination IPs touched — "
            f"source may be probing multiple hosts."
        )

    # Label-vs-prediction sanity.
    if stats.top_label and alert.prediction and stats.top_label != alert.prediction:
        bullets.append(
            f"Ground-truth labels nearby mostly say '{stats.top_label}', "
            f"model predicted '{alert.prediction}' — possible mismatch worth reviewing."
        )

    return summary, bullets


def _format_duration(seconds: float) -> str:
    if seconds < 1:
        return f"{int(seconds * 1000)} ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    if seconds < 3600:
        return f"{seconds / 60:.1f} min"
    if seconds < 86400:
        return f"{seconds / 3600:.1f} h"
    return f"{seconds / 86400:.1f} d"


def _feature_importance(*, top_k: int) -> tuple[list[FeatureImportanceItem], str | None, str | None]:
    """Pull global feature_importances_ from the loaded RF pipeline if possible."""
    bundle = get_model_registry().get()
    if bundle is None:
        return [], None, None

    classifier = None
    pipeline = bundle.pipeline
    named = getattr(pipeline, "named_steps", None) or {}
    if "classifier" in named:
        classifier = named["classifier"]
    if classifier is None or not hasattr(classifier, "feature_importances_"):
        return [], bundle.name, bundle.version

    importances = list(classifier.feature_importances_)
    if len(importances) != len(bundle.feature_order):
        # Defensive: model + metadata disagree on feature count. Skip rather than mislead.
        return [], bundle.name, bundle.version

    pairs = sorted(
        zip(bundle.feature_order, importances, strict=True),
        key=lambda x: x[1],
        reverse=True,
    )[:top_k]
    return (
        [FeatureImportanceItem(feature=f, importance=float(i)) for f, i in pairs],
        bundle.name,
        bundle.version,
    )


# ---------------------------------------------------------------------------
# ORM → DTO converters.
# ---------------------------------------------------------------------------


def _to_related_alert(a: Alert) -> RelatedAlertOut:
    return RelatedAlertOut(
        id=a.id,
        src_ip=a.src_ip,
        dst_ip=a.dst_ip,
        src_port=a.src_port,
        dst_port=a.dst_port,
        protocol=a.protocol,
        prediction=a.prediction,
        severity=a.severity,
        priority=a.priority,
        confidence=a.confidence,
        created_at=a.created_at,
    )


def _to_related_event(e: NetworkEvent) -> RelatedEventOut:
    return RelatedEventOut(
        id=e.id,
        event_time=e.event_time,
        src_ip=e.src_ip,
        dst_ip=e.dst_ip,
        src_port=e.src_port,
        dst_port=e.dst_port,
        protocol=e.protocol,
        label=e.label,
    )
