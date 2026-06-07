"""Reporting Agent service.

Two flavors of report:

* ``generate_alert_report`` — per-alert. Reads from ``alerts``,
  ``agent_decisions``, ``response_actions`` and the most recent
  ``alert_artifacts(INVESTIGATION_PACKET)``. Persists to ``incident_reports``
  with ``kind=PER_ALERT``.
* ``generate_daily_summary`` — daily roll-up. Aggregates by severity / status
  / disposition / source / family + mean latencies. Persists with
  ``kind=DAILY_SUMMARY``.

Both flavors write the structured packet to ``incident_reports.summary``
(JSONB) and the rendered markdown to ``data/reports/report-{id}.md`` on disk
(best-effort — if disk write fails, the markdown is still available inline
through the API).
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, time, timedelta
from datetime import date as date_t
from pathlib import Path
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.events import EventType, publish_event
from app.core.logging import get_logger
from app.models import (
    AgentDecision,
    Alert,
    AlertArtifact,
    IncidentReport,
    ModelVersion,
    ResponseAction,
)
from app.models.enums import (
    AgentName,
    AlertStatus,
    ArtifactKind,
    IncidentKind,
    ResponseStatus,
)
from app.schemas.reporting import (
    AlertReportPacket,
    AnalystEntry,
    AnalystSection,
    DailySummaryPacket,
    DetectionSection,
    FeatureImportanceItem,
    InvestigationSection,
    OverviewSection,
    ResponseActionRow,
    ResponseSection,
    SeverityPrioritySection,
    TimelineRow,
    TimelineSection,
    TriageFactors,
)
from app.services.reporting_renderer import (
    render_alert_report_markdown,
    render_daily_summary_markdown,
)

logger = get_logger(__name__)

TOP_N_AGGREGATES = 10


# ---------------------------------------------------------------------------
# Per-alert report.
# ---------------------------------------------------------------------------


async def generate_alert_report(
    session: AsyncSession,
    alert: Alert,
    *,
    commit: bool = True,
) -> tuple[IncidentReport, AlertReportPacket]:
    """Build + persist a per-alert incident report."""
    decisions = await _load_decisions(session, alert.id)
    actions = await _load_response_actions(session, alert.id)
    investigation_artifact = await _latest_investigation_packet(session, alert.id)
    model_version = await _load_model_version(session, alert.model_version_id)

    detection_decision = _find_decision(decisions, AgentName.DETECTION)
    triage_decision = _find_decision(decisions, AgentName.TRIAGE)
    analyst_decisions = [d for d in decisions if d.agent == AgentName.ANALYST]

    overview = _build_overview(alert, model_version)
    severity_priority = _build_severity_priority(alert, triage_decision)
    detection = _build_detection(detection_decision)
    investigation = _build_investigation(investigation_artifact)
    timeline = _build_timeline(alert, investigation_artifact, decisions, analyst_decisions)
    response = _build_response_section(actions)
    analyst = _build_analyst_section(alert, analyst_decisions)
    final_summary = _build_final_summary(
        alert, detection, triage_decision, investigation, response, analyst_decisions
    )

    title = f"Incident Report — Alert #{alert.id} ({alert.prediction or 'unknown'})"
    packet = AlertReportPacket(
        alert_id=alert.id,
        kind=IncidentKind.PER_ALERT,
        title=title,
        generated_at=datetime.now(UTC),
        workflow_status=alert.status,
        disposition=alert.disposition,
        overview=overview,
        severity_priority=severity_priority,
        detection=detection,
        investigation=investigation,
        timeline=timeline,
        response=response,
        analyst=analyst,
        final_summary=final_summary,
        markdown="",  # filled in below
    )
    packet.markdown = render_alert_report_markdown(packet)

    report = IncidentReport(
        kind=IncidentKind.PER_ALERT,
        alert_id=alert.id,
        title=title,
        summary=packet.model_dump(mode="json"),
    )
    session.add(report)
    await session.flush()
    packet.report_id = report.id

    md_path = _maybe_write_markdown_file(report.id, packet.markdown)
    if md_path is not None:
        report.md_path = str(md_path)

    # Refresh summary now that report_id + markdown are settled.
    report.summary = packet.model_dump(mode="json")

    _advance_alert_to_reported(alert)

    decision = AgentDecision(
        alert_id=alert.id,
        agent=AgentName.REPORTING,
        decision={
            "report_id": report.id,
            "title": title,
            "markdown_bytes": len(packet.markdown),
        },
        reasoning={
            "sections": [
                "overview",
                "severity_priority",
                "detection",
                "investigation",
                "timeline",
                "response",
                "analyst",
                "final_summary",
            ],
            "md_path": str(md_path) if md_path else None,
        },
    )
    session.add(decision)

    if commit:
        await session.commit()
        await session.refresh(report)
        await session.refresh(alert)

    logger.info(
        "report.alert_generated",
        alert_id=alert.id,
        report_id=report.id,
        md_path=str(md_path) if md_path else None,
        actions=len(actions),
    )
    if commit:
        await publish_event(
            EventType.REPORT_CREATED,
            {"report_id": report.id, "alert_id": alert.id, "kind": "PER_ALERT"},
        )
        await publish_event(EventType.ALERT_REPORTED, {"alert_id": alert.id})
    return report, packet


async def get_latest_alert_report(session: AsyncSession, alert_id: int) -> IncidentReport | None:
    stmt = (
        select(IncidentReport)
        .where(
            IncidentReport.alert_id == alert_id,
            IncidentReport.kind == IncidentKind.PER_ALERT,
        )
        .order_by(desc(IncidentReport.created_at))
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Daily summary.
# ---------------------------------------------------------------------------


async def generate_daily_summary(
    session: AsyncSession,
    target_date: date_t | None = None,
    *,
    commit: bool = True,
) -> tuple[IncidentReport, DailySummaryPacket]:
    """Build + persist a daily summary for ``target_date`` (default: today UTC)."""
    if target_date is None:
        target_date = datetime.now(UTC).date()

    period_start = datetime.combine(target_date, time.min, tzinfo=UTC)
    period_end = period_start + timedelta(days=1)

    total_alerts = int(
        (
            await session.execute(
                select(func.count(Alert.id)).where(
                    Alert.created_at >= period_start,
                    Alert.created_at < period_end,
                )
            )
        ).scalar_one()
        or 0
    )

    by_severity = await _group_count(session, Alert.severity, period_start, period_end)
    by_status = await _group_count(session, Alert.status, period_start, period_end)
    by_disposition = await _group_count(session, Alert.disposition, period_start, period_end)

    top_sources = await _top_n(session, Alert.src_ip, period_start, period_end, key="source_ip")
    top_destinations = await _top_n(
        session, Alert.dst_ip, period_start, period_end, key="destination_ip"
    )
    top_predictions = await _top_n(
        session, Alert.prediction, period_start, period_end, key="prediction"
    )

    response_actions_total, by_action_type, by_action_status = await _response_stats(
        session, period_start, period_end
    )
    latencies = await _latency_stats(session, period_start, period_end)

    final_summary = _build_daily_summary_text(
        target_date,
        total_alerts,
        by_severity,
        by_disposition,
        response_actions_total,
        latencies,
    )

    title = f"Daily Security Summary — {target_date.isoformat()}"
    packet = DailySummaryPacket(
        kind=IncidentKind.DAILY_SUMMARY,
        title=title,
        generated_at=datetime.now(UTC),
        date=target_date,
        period_start=period_start,
        period_end=period_end,
        total_alerts=total_alerts,
        by_severity=by_severity,
        by_status=by_status,
        by_disposition=by_disposition,
        top_sources=top_sources,
        top_destinations=top_destinations,
        top_predictions=top_predictions,
        response_actions_total=response_actions_total,
        response_actions_by_type=by_action_type,
        response_actions_by_status=by_action_status,
        mean_triage_latency_seconds=latencies.get("triage"),
        mean_response_latency_seconds=latencies.get("response"),
        mean_investigation_latency_seconds=latencies.get("investigation"),
        mean_report_latency_seconds=latencies.get("report"),
        final_summary=final_summary,
        markdown="",
    )
    packet.markdown = render_daily_summary_markdown(packet)

    report = IncidentReport(
        kind=IncidentKind.DAILY_SUMMARY,
        alert_id=None,
        period_start=period_start,
        period_end=period_end,
        title=title,
        summary=packet.model_dump(mode="json"),
    )
    session.add(report)
    await session.flush()
    packet.report_id = report.id

    md_path = _maybe_write_markdown_file(report.id, packet.markdown)
    if md_path is not None:
        report.md_path = str(md_path)
    report.summary = packet.model_dump(mode="json")

    if commit:
        await session.commit()
        await session.refresh(report)

    logger.info(
        "report.daily_generated",
        report_id=report.id,
        date=target_date.isoformat(),
        total_alerts=total_alerts,
    )
    if commit:
        await publish_event(
            EventType.REPORT_CREATED,
            {
                "report_id": report.id,
                "kind": "DAILY_SUMMARY",
                "date": target_date.isoformat(),
            },
        )
    return report, packet


# ---------------------------------------------------------------------------
# Listing / retrieval.
# ---------------------------------------------------------------------------


async def list_reports(
    session: AsyncSession,
    *,
    kind: IncidentKind | None = None,
    alert_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[IncidentReport]:
    stmt = select(IncidentReport).order_by(desc(IncidentReport.created_at))
    if kind is not None:
        stmt = stmt.where(IncidentReport.kind == kind)
    if alert_id is not None:
        stmt = stmt.where(IncidentReport.alert_id == alert_id)
    stmt = stmt.offset(offset).limit(limit)
    return list((await session.execute(stmt)).scalars().all())


async def get_report(session: AsyncSession, report_id: int) -> IncidentReport | None:
    return await session.get(IncidentReport, report_id)


# ---------------------------------------------------------------------------
# DB helpers.
# ---------------------------------------------------------------------------


async def _load_decisions(session: AsyncSession, alert_id: int) -> list[AgentDecision]:
    stmt = (
        select(AgentDecision)
        .where(AgentDecision.alert_id == alert_id)
        .order_by(AgentDecision.created_at.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def _load_response_actions(session: AsyncSession, alert_id: int) -> list[ResponseAction]:
    stmt = (
        select(ResponseAction)
        .where(ResponseAction.alert_id == alert_id)
        .order_by(ResponseAction.created_at.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def _latest_investigation_packet(
    session: AsyncSession, alert_id: int
) -> dict[str, Any] | None:
    stmt = (
        select(AlertArtifact)
        .where(
            AlertArtifact.alert_id == alert_id,
            AlertArtifact.kind == ArtifactKind.INVESTIGATION_PACKET,
        )
        .order_by(desc(AlertArtifact.created_at))
        .limit(1)
    )
    artifact = (await session.execute(stmt)).scalar_one_or_none()
    return artifact.data if artifact is not None else None


async def _load_model_version(
    session: AsyncSession, model_version_id: int | None
) -> ModelVersion | None:
    if model_version_id is None:
        return None
    return await session.get(ModelVersion, model_version_id)


async def _group_count(
    session: AsyncSession,
    column: Any,
    start: datetime,
    end: datetime,
) -> dict[str, int]:
    stmt = (
        select(column, func.count())
        .where(Alert.created_at >= start, Alert.created_at < end)
        .group_by(column)
    )
    out: dict[str, int] = {}
    for value, count in (await session.execute(stmt)).all():
        key = (
            value.value
            if hasattr(value, "value")
            else (str(value) if value is not None else "UNASSIGNED")
        )
        out[key] = int(count)
    return out


async def _top_n(
    session: AsyncSession,
    column: Any,
    start: datetime,
    end: datetime,
    *,
    key: str,
    n: int = TOP_N_AGGREGATES,
) -> list[dict[str, Any]]:
    stmt = (
        select(column, func.count())
        .where(Alert.created_at >= start, Alert.created_at < end)
        .group_by(column)
        .order_by(func.count().desc())
        .limit(n)
    )
    return [
        {key: (str(value) if value is not None else "—"), "count": int(count)}
        for value, count in (await session.execute(stmt)).all()
    ]


async def _response_stats(
    session: AsyncSession, start: datetime, end: datetime
) -> tuple[int, dict[str, int], dict[str, int]]:
    total = int(
        (
            await session.execute(
                select(func.count(ResponseAction.id)).where(
                    ResponseAction.created_at >= start,
                    ResponseAction.created_at < end,
                )
            )
        ).scalar_one()
        or 0
    )

    by_type_rows = (
        await session.execute(
            select(ResponseAction.action_type, func.count())
            .where(
                ResponseAction.created_at >= start,
                ResponseAction.created_at < end,
            )
            .group_by(ResponseAction.action_type)
        )
    ).all()
    by_status_rows = (
        await session.execute(
            select(ResponseAction.status, func.count())
            .where(
                ResponseAction.created_at >= start,
                ResponseAction.created_at < end,
            )
            .group_by(ResponseAction.status)
        )
    ).all()

    by_type = {(v.value if hasattr(v, "value") else str(v)): int(c) for v, c in by_type_rows}
    by_status = {(v.value if hasattr(v, "value") else str(v)): int(c) for v, c in by_status_rows}
    return total, by_type, by_status


async def _latency_stats(
    session: AsyncSession, start: datetime, end: datetime
) -> dict[str, float | None]:
    """Mean Detection → next-stage latency in seconds. NULL stage rows are skipped by AVG."""
    cols = [
        func.avg(func.extract("epoch", Alert.triaged_at - Alert.created_at)),
        func.avg(func.extract("epoch", Alert.responded_at - Alert.created_at)),
        func.avg(func.extract("epoch", Alert.investigated_at - Alert.created_at)),
        func.avg(func.extract("epoch", Alert.reported_at - Alert.created_at)),
    ]
    row = (
        await session.execute(
            select(*cols).where(Alert.created_at >= start, Alert.created_at < end)
        )
    ).one()
    keys = ("triage", "response", "investigation", "report")
    return {k: (float(v) if v is not None else None) for k, v in zip(keys, row, strict=True)}


# ---------------------------------------------------------------------------
# Section builders — pure(ish), no DB calls inside.
# ---------------------------------------------------------------------------


def _find_decision(decisions: list[AgentDecision], agent: AgentName) -> AgentDecision | None:
    return next((d for d in decisions if d.agent == agent), None)


def _build_overview(alert: Alert, model_version: ModelVersion | None) -> OverviewSection:
    name = model_version.name if model_version is not None else None
    version = model_version.version if model_version is not None else None
    return OverviewSection(
        alert_id=alert.id,
        created_at=alert.created_at,
        src_ip=alert.src_ip,
        src_port=alert.src_port,
        dst_ip=alert.dst_ip,
        dst_port=alert.dst_port,
        protocol=alert.protocol,
        prediction=alert.prediction,
        model_name=name,
        model_version=version,
    )


def _build_severity_priority(
    alert: Alert, triage_decision: AgentDecision | None
) -> SeverityPrioritySection:
    factors_dict: dict[str, Any] = {}
    explanations: list[str] = []
    weights: dict[str, float] = {}
    if triage_decision is not None:
        reasoning = triage_decision.reasoning or {}
        factors_dict = reasoning.get("factors", {}) or {}
        explanations = list(reasoning.get("explanations", []) or [])
        weights = dict(reasoning.get("component_weights", {}) or {})

    factors = TriageFactors(
        family=factors_dict.get("family"),
        family_score=factors_dict.get("family_score"),
        confidence_score=factors_dict.get("confidence_score"),
        dst_port=factors_dict.get("dst_port"),
        port_score=factors_dict.get("port_score"),
        volume_score=factors_dict.get("volume_score"),
    )
    return SeverityPrioritySection(
        severity=alert.severity,
        priority=alert.priority,
        factors=factors,
        component_weights=weights,
        explanations=explanations,
        triaged_at=alert.triaged_at,
    )


def _build_detection(
    detection_decision: AgentDecision | None,
) -> DetectionSection | None:
    if detection_decision is None:
        return None
    d = detection_decision.decision or {}
    r = detection_decision.reasoning or {}
    return DetectionSection(
        predicted_label=str(d.get("predicted_label", "")),
        confidence=float(d.get("confidence") or 0.0),
        threshold=(float(r["threshold"]) if r.get("threshold") is not None else None),
        class_probabilities={k: float(v) for k, v in (r.get("class_probabilities") or {}).items()},
        model_name=r.get("model_name"),
        model_version=r.get("model_version"),
    )


def _build_investigation(
    packet_data: dict[str, Any] | None,
) -> InvestigationSection:
    if packet_data is None:
        return InvestigationSection(available=False)

    feature_importance = [
        FeatureImportanceItem(
            feature=fi.get("feature", "?"), importance=float(fi.get("importance", 0.0))
        )
        for fi in (packet_data.get("feature_importance") or [])
    ]

    generated_at_raw = packet_data.get("generated_at")
    try:
        generated_at = datetime.fromisoformat(generated_at_raw) if generated_at_raw else None
    except (TypeError, ValueError):
        generated_at = None

    return InvestigationSection(
        available=True,
        summary=packet_data.get("summary"),
        bullets=list(packet_data.get("summary_bullets") or []),
        statistics=dict(packet_data.get("statistics") or {}),
        feature_importance=feature_importance,
        generated_at=generated_at,
    )


def _build_timeline(
    alert: Alert,
    investigation_packet: dict[str, Any] | None,
    decisions: list[AgentDecision],
    analyst_decisions: list[AgentDecision],
) -> TimelineSection:
    items: list[TimelineRow] = []

    if investigation_packet is not None:
        for t in investigation_packet.get("timeline", []) or []:
            try:
                ts = datetime.fromisoformat(t["timestamp"])
            except (TypeError, ValueError, KeyError):
                continue
            items.append(
                TimelineRow(
                    timestamp=ts,
                    kind=str(t.get("kind", "event")),
                    summary=str(t.get("summary", "")),
                    is_current_alert=bool(t.get("is_current_alert", False)),
                )
            )
    else:
        # Synthesize from alert + decisions.
        items.append(
            TimelineRow(
                timestamp=alert.created_at,
                kind="alert",
                summary=f"▶ Alert #{alert.id} created ({alert.prediction})",
                is_current_alert=True,
            )
        )

    # Always add agent + analyst events from agent_decisions.
    for d in decisions:
        if d.agent == AgentName.DETECTION:
            label = (d.decision or {}).get("predicted_label", alert.prediction)
            conf = (d.decision or {}).get("confidence", alert.confidence)
            items.append(
                TimelineRow(
                    timestamp=d.created_at,
                    kind="agent",
                    summary=f"Detection: {label} (confidence {conf:.2f})",
                )
            )
        elif d.agent == AgentName.TRIAGE:
            dec = d.decision or {}
            items.append(
                TimelineRow(
                    timestamp=d.created_at,
                    kind="agent",
                    summary=(
                        f"Triage: severity={dec.get('severity', '?')}, "
                        f"priority={dec.get('priority', 0):.1f}"
                    ),
                )
            )
        elif d.agent == AgentName.RESPONSE:
            dec = d.decision or {}
            items.append(
                TimelineRow(
                    timestamp=d.created_at,
                    kind="agent",
                    summary=(
                        f"Response: {dec.get('n_recommendations', 0)} action(s) "
                        f"({dec.get('n_auto_executed', 0)} auto, "
                        f"{dec.get('n_awaiting_approval', 0)} pending)"
                    ),
                )
            )
        elif d.agent == AgentName.INVESTIGATION:
            dec = d.decision or {}
            items.append(
                TimelineRow(
                    timestamp=d.created_at,
                    kind="agent",
                    summary=(
                        f"Investigation: {dec.get('n_related_events', 0)} events, "
                        f"{dec.get('n_related_alerts', 0)} related alerts"
                    ),
                )
            )

    for d in analyst_decisions:
        items.append(
            TimelineRow(
                timestamp=d.created_at,
                kind="analyst",
                summary=_format_analyst_summary(d),
            )
        )

    items.sort(key=lambda x: x.timestamp)
    return TimelineSection(items=items)


def _build_response_section(actions: list[ResponseAction]) -> ResponseSection:
    rows = [
        ResponseActionRow(
            id=a.id,
            action_type=a.action_type,
            status=a.status,
            approval_required=a.approval_required,
            executed=a.executed,
            approved_by=a.approved_by,
            rejection_reason=a.rejection_reason,
            rationale=(a.payload or {}).get("rationale") if isinstance(a.payload, dict) else None,
            payload=a.payload or {},
            executed_at=a.executed_at,
            created_at=a.created_at,
        )
        for a in actions
    ]
    counts_by_status: dict[str, int] = Counter(r.status.value for r in rows)
    auto = sum(1 for a in actions if a.executed and not a.approval_required)
    awaiting = sum(1 for a in actions if a.status == ResponseStatus.PENDING)
    rejected = sum(1 for a in actions if a.status == ResponseStatus.REJECTED)
    return ResponseSection(
        actions=rows,
        counts_by_status=dict(counts_by_status),
        auto_executed=auto,
        awaiting_approval=awaiting,
        rejected=rejected,
    )


def _build_analyst_section(alert: Alert, analyst_decisions: list[AgentDecision]) -> AnalystSection:
    entries: list[AnalystEntry] = []
    for d in analyst_decisions:
        dec = d.decision or {}
        reasoning = d.reasoning or {}
        verb = str(dec.get("verb", "action"))
        target_action = dec.get("action_type") or dec.get("action_id")
        target_disp = dec.get("disposition_to")
        target = str(target_disp if target_disp else target_action or "")
        entries.append(
            AnalystEntry(
                timestamp=d.created_at,
                analyst_id=reasoning.get("analyst_id"),
                verb=verb,
                target=target or None,
                note=reasoning.get("note") or reasoning.get("reason"),
                detail=_format_analyst_summary(d),
            )
        )
    return AnalystSection(
        status=alert.status,
        disposition=alert.disposition,
        entries=entries,
    )


def _format_analyst_summary(d: AgentDecision) -> str:
    dec = d.decision or {}
    reasoning = d.reasoning or {}
    note = reasoning.get("note") or reasoning.get("reason") or ""
    note_suffix = f" — “{note.strip()}”" if note and isinstance(note, str) else ""

    if "disposition_to" in dec:
        return (
            f"Disposition changed: {dec.get('disposition_from', '?')} → "
            f"{dec['disposition_to']}{note_suffix}"
        )
    verb = dec.get("verb", "action")
    target = dec.get("action_type") or f"action#{dec.get('action_id', '?')}"
    return f"{verb.upper()} on {target}{note_suffix}"


def _build_final_summary(
    alert: Alert,
    detection: DetectionSection | None,
    triage_decision: AgentDecision | None,
    investigation: InvestigationSection,
    response: ResponseSection,
    analyst_decisions: list[AgentDecision],
) -> str:
    parts: list[str] = []

    if detection is not None:
        model = (
            f" by `{detection.model_name}@{detection.model_version}`"
            if detection.model_name
            else ""
        )
        parts.append(
            f"Alert #{alert.id} was classified as **{detection.predicted_label}** "
            f"with {detection.confidence:.2f} confidence{model}."
        )
    else:
        parts.append(f"Alert #{alert.id} ({alert.prediction}) has no detection-agent record.")

    if triage_decision is not None:
        d = triage_decision.decision or {}
        parts.append(
            f"Triage assigned **{d.get('severity', '?')}** severity "
            f"(priority {float(d.get('priority', 0)):.1f})."
        )

    if investigation.available:
        stats = investigation.statistics or {}
        related = int(stats.get("related_alert_count", 0))
        same_family = int(stats.get("same_family_alert_count", 0))
        if related > 0:
            extra = f", {same_family} sharing the same predicted family" if same_family > 0 else ""
            parts.append(
                f"Investigation found {related} related alert(s) in the surrounding window{extra}."
            )
        else:
            parts.append("Investigation found no related alerts in the window.")
    else:
        parts.append("No investigation packet attached.")

    if response.actions:
        if response.auto_executed > 0:
            executed_types = sorted({a.action_type.value for a in response.actions if a.executed})
            parts.append(
                f"Response auto-executed **{response.auto_executed}** action(s): "
                f"{', '.join(executed_types) or '—'}."
            )
        if response.awaiting_approval > 0:
            parts.append(f"**{response.awaiting_approval}** action(s) await analyst approval.")
        if response.rejected > 0:
            parts.append(f"**{response.rejected}** action(s) were rejected.")
    else:
        parts.append("No response actions were recommended.")

    if analyst_decisions:
        parts.append(f"Analyst recorded {len(analyst_decisions)} action(s).")

    parts.append(
        f"Current state: status `{alert.status.value}`, disposition `{alert.disposition.value}`."
    )
    return " ".join(parts)


def _build_daily_summary_text(
    target_date: date_t,
    total_alerts: int,
    by_severity: dict[str, int],
    by_disposition: dict[str, int],
    response_actions_total: int,
    latencies: dict[str, float | None],
) -> str:
    if total_alerts == 0:
        return (
            f"No alerts were recorded on {target_date.isoformat()}. "
            "Either the ingestion pipeline was idle or all flows were classified benign."
        )

    critical = by_severity.get("CRITICAL", 0)
    high = by_severity.get("HIGH", 0)
    fps = by_disposition.get("FALSE_POSITIVE", 0)
    triage_ms = latencies.get("triage")
    triage_str = f"{triage_ms:.2f}s" if triage_ms is not None else "—"

    parts = [
        f"{total_alerts} alert(s) were created on {target_date.isoformat()} "
        f"({critical} CRITICAL, {high} HIGH).",
        f"{response_actions_total} response action(s) were generated.",
        f"Mean Detection→Triage latency: {triage_str}.",
    ]
    if fps:
        parts.append(f"{fps} alert(s) were marked FALSE_POSITIVE by analysts.")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Misc.
# ---------------------------------------------------------------------------


def _advance_alert_to_reported(alert: Alert) -> None:
    if alert.status in {
        AlertStatus.NEW,
        AlertStatus.TRIAGED,
        AlertStatus.AUTO_RESPONDED,
        AlertStatus.AWAITING_ANALYST,
        AlertStatus.INVESTIGATED,
    }:
        alert.status = AlertStatus.REPORTED
    alert.reported_at = datetime.now(UTC)


def _maybe_write_markdown_file(report_id: int, markdown: str) -> Path | None:
    """Best-effort: write the markdown to disk. Failure is non-fatal."""
    settings = get_settings()
    try:
        out_dir = Path(settings.reports_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"report-{report_id}.md"
        path.write_text(markdown, encoding="utf-8")
        return path
    except OSError as exc:
        logger.warning(
            "report.markdown_write_failed",
            report_id=report_id,
            error=str(exc),
        )
        return None
