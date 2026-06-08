"""Reports API.

Surface:

    GET  /api/v1/reports               — list reports (filter by kind / alert_id)
    GET  /api/v1/reports/{id}          — return the full packet (structured + markdown)
    GET  /api/v1/reports/{id}/markdown — raw markdown (text/markdown)
    POST /api/v1/reports/daily/run     — generate a daily summary; body: {date?}
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import SessionDep, rate_limit
from app.api.pagination import set_total_count
from app.core.errors import NotFoundError
from app.models.enums import IncidentKind
from app.schemas.reporting import (
    DailySummaryEnvelope,
    DailySummaryRequest,
    IncidentReportOut,
)
from app.services.reporting_service import (
    count_reports,
    generate_daily_summary,
    get_report,
    list_reports,
)

router = APIRouter(prefix="/reports")


@router.get("")
async def list_reports_endpoint(
    session: SessionDep,
    response: Response,
    kind: Annotated[IncidentKind | None, Query()] = None,
    alert_id: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[IncidentReportOut]:
    set_total_count(response, await count_reports(session, kind=kind, alert_id=alert_id))
    rows = await list_reports(session, kind=kind, alert_id=alert_id, limit=limit, offset=offset)
    return [IncidentReportOut.model_validate(r) for r in rows]


@router.post(
    "/daily/run",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit("report"))],
)
async def daily_run(
    session: SessionDep, request: DailySummaryRequest | None = None
) -> DailySummaryEnvelope:
    req = request or DailySummaryRequest()
    report, packet = await generate_daily_summary(session, req.date)
    return DailySummaryEnvelope(report_id=report.id, packet=packet)


@router.get("/{report_id}")
async def get_report_endpoint(session: SessionDep, report_id: int) -> dict:
    report = await get_report(session, report_id)
    if report is None:
        raise NotFoundError(f"IncidentReport {report_id} not found.")
    # The structured packet lives in summary JSONB; return it verbatim with a
    # tiny envelope of identifiers so the dashboard knows where it came from.
    return {
        "id": report.id,
        "kind": report.kind.value if hasattr(report.kind, "value") else str(report.kind),
        "alert_id": report.alert_id,
        "title": report.title,
        "md_path": report.md_path,
        "pdf_path": report.pdf_path,
        "created_at": report.created_at.isoformat(),
        "updated_at": report.updated_at.isoformat(),
        "packet": report.summary,
    }


@router.get("/{report_id}/markdown", response_class=Response)
async def get_report_markdown(session: SessionDep, report_id: int) -> Response:
    report = await get_report(session, report_id)
    if report is None:
        raise NotFoundError(f"IncidentReport {report_id} not found.")
    markdown = (report.summary or {}).get("markdown", "")
    return Response(content=markdown, media_type="text/markdown; charset=utf-8")
