"""Ingestion API.

Surface:

    POST /api/v1/ingest/upload   multipart CSV upload
    POST /api/v1/ingest/replay   ingest a CSV under the server-side data dir
    POST /api/v1/ingest/flow     single-record ingest
    POST /api/v1/ingest/flows    batch ingest (live sensor)
    GET  /api/v1/ingest/jobs     list jobs
    GET  /api/v1/ingest/jobs/{id}  single job detail
    GET  /api/v1/ingest/sensor/status  live-sensor activity proxy
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status
from pydantic import ValidationError
from sqlalchemy import desc, func, select

from app.api.deps import SessionDep, rate_limit
from app.api.pagination import set_total_count
from app.core.config import get_settings
from app.core.errors import AppError, BadRequestError, NotFoundError
from app.core.logging import get_logger
from app.ingestion.csv_loader import CsvFormatError
from app.ingestion.parser import ParsedFlow
from app.models import IngestionJob
from app.models.enums import IngestionKind
from app.schemas.ingestion import (
    FlowBatchIn,
    FlowBatchSummary,
    FlowRecordIn,
    FlowRecordOut,
    IngestionJobOut,
    IngestionSummary,
    ReplayRequest,
    SensorStatusOut,
)
from app.services.detection_service import detect_events, fetch_undetected_events
from app.services.ingestion_service import (
    ingest_csv,
    insert_flow_batch,
    insert_single_flow,
    sensor_status,
)
from app.services.model_registry import get_model_registry

router = APIRouter(prefix="/ingest")
logger = get_logger(__name__)


@router.post(
    "/upload",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("ingest"))],
)
async def upload_csv(
    session: SessionDep,
    file: Annotated[UploadFile, File(description="CSV file with one flow per row.")],
) -> IngestionSummary:
    """Upload a CSV via multipart form-data and ingest it synchronously."""
    settings = get_settings()

    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise AppError("Upload must be a .csv file.")
    if file.size is not None and file.size > settings.ingest_max_upload_bytes:
        raise AppError(
            f"File exceeds {settings.ingest_max_upload_bytes} bytes.",
            details={"size": file.size, "limit": settings.ingest_max_upload_bytes},
        )

    try:
        return await ingest_csv(
            session,
            file=file.file,
            source=file.filename,
            kind=IngestionKind.REPLAY,
        )
    except CsvFormatError as exc:
        raise AppError(str(exc)) from exc


@router.post(
    "/replay",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("ingest"))],
)
async def replay(session: SessionDep, request: ReplayRequest) -> IngestionSummary:
    """Ingest a CSV that already lives under the server-side data dir.

    The path must be relative; absolute paths and ``..`` traversal are rejected.
    """
    settings = get_settings()
    data_root = Path(settings.ingest_data_dir).resolve()
    requested = Path(request.file)

    if requested.is_absolute() or any(part == ".." for part in requested.parts):
        raise AppError("Path must be relative and may not contain '..'.")

    target = (data_root / requested).resolve()
    if not _is_within(target, data_root):
        raise AppError("Path escapes the configured data directory.")
    if not target.is_file():
        raise NotFoundError(
            f"File not found: {request.file}",
            details={"data_root": str(data_root)},
        )

    try:
        with target.open("rb") as fh:
            return await ingest_csv(
                session,
                file=fh,
                source=str(requested),
                kind=IngestionKind.REPLAY,
                rate_limit=request.rate,
            )
    except CsvFormatError as exc:
        raise AppError(str(exc)) from exc


@router.post(
    "/flow",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("ingest"))],
)
async def ingest_flow(session: SessionDep, flow: FlowRecordIn) -> FlowRecordOut:
    """Ingest a single flow record. Useful for live producers and tests."""
    parsed = ParsedFlow.model_validate(flow.model_dump())
    event = await insert_single_flow(session, parsed)
    return FlowRecordOut.model_validate(event)


@router.post(
    "/flows",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("ingest"))],
)
async def ingest_flows(session: SessionDep, batch: FlowBatchIn) -> FlowBatchSummary:
    """Batch-ingest flows from the live sensor (Zeek/Suricata/pcap-replay).

    Requires ANALYST+ (method-based RBAC) — the sensor authenticates with a
    service/analyst JWT. When ``SENTINEL_DETECTION_AUTO_RUN_ON_INGEST`` is set,
    detection runs on the freshly-queued events right after insert (bounded);
    failures there never fail the ingest, which is already committed.
    """
    settings = get_settings()
    try:
        parsed = [ParsedFlow.model_validate(f.model_dump()) for f in batch.flows]
    except ValidationError as exc:
        # Keep only JSON-safe fields (pydantic's ctx can hold raw exceptions).
        errors = [
            {"loc": list(e.get("loc", ())), "msg": str(e.get("msg")), "type": str(e.get("type"))}
            for e in exc.errors()[:20]
        ]
        raise BadRequestError(
            "One or more flows failed validation.", details={"errors": errors}
        ) from exc
    inserted = await insert_flow_batch(session, parsed)

    detection_ran = False
    alerts_created = 0
    if settings.detection_auto_run_on_ingest and get_model_registry().is_loaded():
        try:
            bundle = get_model_registry().get()
            events = await fetch_undetected_events(session, settings.detection_auto_run_limit)
            if events and bundle is not None:
                predictions = await detect_events(
                    session,
                    bundle,
                    events,
                    threshold=settings.detection_threshold,
                    benign_label=settings.detection_benign_label,
                    class_thresholds=settings.detection_class_thresholds,
                )
                detection_ran = True
                alerts_created = sum(1 for p in predictions if p.alert_created)
        except Exception:
            logger.exception("ingest.auto_detection_failed")

    return FlowBatchSummary(
        received=len(batch.flows),
        inserted=inserted,
        detection_ran=detection_ran,
        alerts_created=alerts_created,
    )


@router.get("/sensor/status")
async def get_sensor_status(session: SessionDep) -> SensorStatusOut:
    """Live-sensor liveness proxy (recent ingest activity). VIEWER+."""
    settings = get_settings()
    status_data = await sensor_status(
        session, live_window_seconds=settings.sensor_live_window_seconds
    )
    return SensorStatusOut.model_validate(status_data)


@router.get("/jobs")
async def list_jobs(
    session: SessionDep,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[IngestionJobOut]:
    total = (await session.execute(select(func.count(IngestionJob.id)))).scalar_one() or 0
    set_total_count(response, int(total))
    result = await session.execute(
        select(IngestionJob).order_by(desc(IngestionJob.created_at)).offset(offset).limit(limit)
    )
    return [IngestionJobOut.model_validate(j) for j in result.scalars().all()]


@router.get("/jobs/{job_id}")
async def get_job(session: SessionDep, job_id: int) -> IngestionJobOut:
    job = await session.get(IngestionJob, job_id)
    if job is None:
        raise NotFoundError(f"IngestionJob {job_id} not found.")
    return IngestionJobOut.model_validate(job)


def _is_within(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True
