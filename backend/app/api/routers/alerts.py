"""Alert listing, detail, triage, disposition, and stats endpoints.

Detection auto-triages new alerts in the same transaction, so this router's
write paths are mostly for analyst-driven flows: manual re-triage,
disposition updates (false-positive / confirmed / …), and bulk close.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import String, cast, desc, func, or_, select
from sqlalchemy.orm import selectinload

from app.api.deps import SessionDep, rate_limit
from app.core.errors import NotFoundError
from app.models import Alert
from app.models.enums import AlertDisposition, AlertStatus, Severity
from app.schemas.alert import (
    AlertDecisionOut,
    AlertDetailOut,
    AlertOut,
    AlertStatsOut,
    AlertTimeseriesOut,
    AlertTimeseriesPoint,
    CloseAlertRequest,
    TriageOut,
    TriageRequest,
    UpdateDispositionRequest,
)
from app.schemas.investigation import (
    InvestigateRequest,
    InvestigationOut,
    InvestigationPacket,
)
from app.schemas.reporting import (
    AlertReportEnvelope,
    AlertReportPacket,
    ReportRequest,
)
from app.schemas.response import ResponseActionOut
from app.services.investigation_service import (
    get_latest_investigation,
    investigate_alert,
)
from app.services.reporting_service import (
    generate_alert_report,
    get_latest_alert_report,
)
from app.services.triage_service import (
    close_alert as svc_close_alert,
)
from app.services.triage_service import (
    triage_alert,
    update_disposition,
)

router = APIRouter(prefix="/alerts")

SortKey = Literal["created_at", "priority", "severity"]


@router.get("")
async def list_alerts(
    session: SessionDep,
    status_filter: Annotated[AlertStatus | None, Query(alias="status")] = None,
    severity: Annotated[Severity | None, Query()] = None,
    disposition: Annotated[AlertDisposition | None, Query()] = None,
    src_ip: Annotated[str | None, Query()] = None,
    dst_ip: Annotated[str | None, Query()] = None,
    prediction: Annotated[str | None, Query()] = None,
    min_priority: Annotated[float | None, Query(ge=0, le=100)] = None,
    q: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    sort: Annotated[SortKey, Query()] = "created_at",
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[AlertOut]:
    stmt = select(Alert)
    if status_filter is not None:
        stmt = stmt.where(Alert.status == status_filter)
    if severity is not None:
        stmt = stmt.where(Alert.severity == severity)
    if disposition is not None:
        stmt = stmt.where(Alert.disposition == disposition)
    if src_ip:
        stmt = stmt.where(Alert.src_ip == src_ip)
    if dst_ip:
        stmt = stmt.where(Alert.dst_ip == dst_ip)
    if prediction:
        stmt = stmt.where(Alert.prediction == prediction)
    if min_priority is not None:
        stmt = stmt.where(Alert.priority >= min_priority)
    if q:
        # Substring match against src_ip / dst_ip / prediction (case-insensitive).
        # INET is cast to text so ILIKE can operate on it.
        pattern = f"%{q}%"
        stmt = stmt.where(
            or_(
                cast(Alert.src_ip, String).ilike(pattern),
                cast(Alert.dst_ip, String).ilike(pattern),
                Alert.prediction.ilike(pattern),
            )
        )

    if sort == "priority":
        # NULLS LAST so un-triaged rows sink to the bottom of the dashboard.
        stmt = stmt.order_by(Alert.priority.desc().nulls_last(), desc(Alert.created_at))
    elif sort == "severity":
        # CRITICAL > HIGH > MEDIUM > LOW > NULL. Use a CASE for stable ordering.
        severity_order = {
            Severity.CRITICAL.value: 4,
            Severity.HIGH.value: 3,
            Severity.MEDIUM.value: 2,
            Severity.LOW.value: 1,
        }
        from sqlalchemy import case

        sev_case = case(severity_order, value=Alert.severity, else_=0)
        stmt = stmt.order_by(sev_case.desc(), desc(Alert.created_at))
    else:
        stmt = stmt.order_by(desc(Alert.created_at))

    stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    return [AlertOut.model_validate(a) for a in result.scalars().all()]


@router.get("/stats")
async def alert_stats(session: SessionDep) -> AlertStatsOut:
    total = int((await session.execute(select(func.count(Alert.id)))).scalar_one() or 0)

    async def _group(col):
        rows = (await session.execute(select(col, func.count()).group_by(col))).all()
        return {
            (v.value if hasattr(v, "value") else (str(v) if v is not None else "UNASSIGNED")): int(
                c
            )
            for v, c in rows
        }

    return AlertStatsOut(
        total=total,
        by_status=await _group(Alert.status),
        by_severity=await _group(Alert.severity),
        by_disposition=await _group(Alert.disposition),
        by_prediction=await _group(Alert.prediction),
    )


@router.get("/timeseries")
async def alert_timeseries(
    session: SessionDep,
    hours: Annotated[int, Query(ge=1, le=720)] = 24,
) -> AlertTimeseriesOut:
    """Hourly alert counts for the last ``hours``, broken down by severity.

    Empty buckets are zero-filled so the line chart has no gaps.
    """
    end = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    start = end - timedelta(hours=hours)

    bucket_col = func.date_trunc("hour", Alert.created_at).label("bucket")
    rows = (
        await session.execute(
            select(bucket_col, Alert.severity, func.count())
            .where(Alert.created_at >= start)
            .group_by(bucket_col, Alert.severity)
            .order_by(bucket_col)
        )
    ).all()

    by_bucket: dict[datetime, dict[str, int]] = {}
    for b, sev, c in rows:
        if b is None:
            continue
        # Postgres returns timezone-aware datetimes for timestamptz; normalize to UTC.
        if b.tzinfo is None:
            b = b.replace(tzinfo=UTC)
        sev_key = sev.value if hasattr(sev, "value") else (str(sev) if sev else "UNRATED")
        by_bucket.setdefault(b, {})[sev_key] = int(c)

    # Zero-fill every hour in the window.
    points: list[AlertTimeseriesPoint] = []
    cursor = start
    while cursor < end:
        bucket = by_bucket.get(cursor, {})
        low = bucket.get("LOW", 0)
        med = bucket.get("MEDIUM", 0)
        high = bucket.get("HIGH", 0)
        crit = bucket.get("CRITICAL", 0)
        unrated = bucket.get("UNRATED", 0) + bucket.get("UNASSIGNED", 0)
        points.append(
            AlertTimeseriesPoint(
                bucket=cursor,
                LOW=low,
                MEDIUM=med,
                HIGH=high,
                CRITICAL=crit,
                UNRATED=unrated,
                total=low + med + high + crit + unrated,
            )
        )
        cursor += timedelta(hours=1)

    return AlertTimeseriesOut(bucket="hour", period_hours=hours, points=points)


@router.get("/{alert_id}")
async def get_alert(session: SessionDep, alert_id: int) -> AlertDetailOut:
    stmt = (
        select(Alert)
        .where(Alert.id == alert_id)
        .options(selectinload(Alert.decisions), selectinload(Alert.actions))
    )
    alert = (await session.execute(stmt)).scalar_one_or_none()
    if alert is None:
        raise NotFoundError(f"Alert {alert_id} not found.")
    return AlertDetailOut.model_validate(
        {
            **AlertOut.model_validate(alert).model_dump(),
            "decisions": [AlertDecisionOut.model_validate(d) for d in alert.decisions],
            "actions": [ResponseActionOut.model_validate(a) for a in alert.actions],
        }
    )


@router.post("/{alert_id}/triage", status_code=status.HTTP_200_OK)
async def triage(
    session: SessionDep,
    alert_id: int,
    request: TriageRequest | None = None,
) -> TriageOut:
    alert = await session.get(Alert, alert_id)
    if alert is None:
        raise NotFoundError(f"Alert {alert_id} not found.")

    window = (request or TriageRequest()).window_minutes
    score = await triage_alert(session, alert, window_minutes=window, commit=True)
    return TriageOut(
        alert_id=alert.id,
        severity=Severity(score.severity),
        priority=score.priority,
        recent_count=score.recent_count,
        component_weights=score.component_weights,
        factors={
            "family": score.family,
            "family_score": score.family_score,
            "confidence_score": score.confidence_score,
            "dst_port": score.dst_port,
            "port_score": score.port_score,
            "volume_score": score.volume_score,
        },
        explanations=score.explanations,
    )


@router.post("/{alert_id}/disposition", status_code=status.HTTP_200_OK)
async def set_disposition(
    session: SessionDep,
    alert_id: int,
    request: UpdateDispositionRequest,
) -> AlertOut:
    alert = await session.get(Alert, alert_id)
    if alert is None:
        raise NotFoundError(f"Alert {alert_id} not found.")
    updated = await update_disposition(
        session,
        alert,
        request.disposition,
        analyst_id=request.analyst_id,
        note=request.note,
    )
    return AlertOut.model_validate(updated)


@router.post("/{alert_id}/investigate", status_code=status.HTTP_200_OK)
async def investigate(
    session: SessionDep,
    alert_id: int,
    request: InvestigateRequest | None = None,
) -> InvestigationOut:
    alert = await session.get(Alert, alert_id)
    if alert is None:
        raise NotFoundError(f"Alert {alert_id} not found.")

    req = request or InvestigateRequest()
    artifact, packet = await investigate_alert(
        session,
        alert,
        events_window_minutes=req.events_window_minutes,
        alerts_window_hours=req.alerts_window_hours,
        max_events=req.max_events,
        max_alerts=req.max_alerts,
    )
    return InvestigationOut(artifact_id=artifact.id, packet=packet)


# Alias kept for backwards-compatibility with earlier docs/architecture.
@router.post("/{alert_id}/reinvestigate", status_code=status.HTTP_200_OK)
async def reinvestigate(
    session: SessionDep,
    alert_id: int,
    request: InvestigateRequest | None = None,
) -> InvestigationOut:
    return await investigate(session, alert_id, request)


@router.get("/{alert_id}/investigation")
async def get_alert_investigation(session: SessionDep, alert_id: int) -> InvestigationOut:
    """Return the most recent investigation packet for an alert (without re-running)."""
    artifact = await get_latest_investigation(session, alert_id)
    if artifact is None:
        raise NotFoundError(
            f"No investigation packet found for alert {alert_id}.",
            details={"alert_id": alert_id, "hint": "POST /investigate first."},
        )
    return InvestigationOut(
        artifact_id=artifact.id,
        packet=InvestigationPacket.model_validate(artifact.data),
    )


@router.post(
    "/{alert_id}/report",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit("report"))],
)
async def generate_alert_report_endpoint(
    session: SessionDep,
    alert_id: int,
    request: ReportRequest | None = None,
) -> AlertReportEnvelope:
    """Generate (and persist) an incident report for this alert."""
    _ = request  # reserved for future toggles
    alert = await session.get(Alert, alert_id)
    if alert is None:
        raise NotFoundError(f"Alert {alert_id} not found.")
    report, packet = await generate_alert_report(session, alert)
    return AlertReportEnvelope(report_id=report.id, packet=packet)


@router.get("/{alert_id}/report")
async def get_alert_report_endpoint(session: SessionDep, alert_id: int) -> AlertReportEnvelope:
    """Return the most recent incident report for this alert (no re-generation)."""
    report = await get_latest_alert_report(session, alert_id)
    if report is None:
        raise NotFoundError(
            f"No incident report found for alert {alert_id}.",
            details={"alert_id": alert_id, "hint": "POST /report first."},
        )
    packet = AlertReportPacket.model_validate(report.summary)
    packet.report_id = report.id
    return AlertReportEnvelope(report_id=report.id, packet=packet)


@router.post("/{alert_id}/close", status_code=status.HTTP_200_OK)
async def close_alert(
    session: SessionDep,
    alert_id: int,
    request: CloseAlertRequest | None = None,
) -> AlertOut:
    alert = await session.get(Alert, alert_id)
    if alert is None:
        raise NotFoundError(f"Alert {alert_id} not found.")
    req = request or CloseAlertRequest()
    updated = await svc_close_alert(session, alert, analyst_id=req.analyst_id, note=req.note)
    return AlertOut.model_validate(updated)
