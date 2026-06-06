"""Ingestion API.

Surface:

    POST /api/v1/ingest/upload   multipart CSV upload
    POST /api/v1/ingest/replay   ingest a CSV under the server-side data dir
    POST /api/v1/ingest/flow     single-record ingest
    GET  /api/v1/ingest/jobs     list jobs
    GET  /api/v1/ingest/jobs/{id}  single job detail
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Query, UploadFile, status
from sqlalchemy import desc, select

from app.api.deps import SessionDep
from app.core.config import get_settings
from app.core.errors import AppError, NotFoundError
from app.ingestion.csv_loader import CsvFormatError
from app.ingestion.parser import ParsedFlow
from app.models import IngestionJob
from app.models.enums import IngestionKind
from app.schemas.ingestion import (
    FlowRecordIn,
    FlowRecordOut,
    IngestionJobOut,
    IngestionSummary,
    ReplayRequest,
)
from app.services.ingestion_service import ingest_csv, insert_single_flow

router = APIRouter(prefix="/ingest")


@router.post("/upload", status_code=status.HTTP_201_CREATED)
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


@router.post("/replay", status_code=status.HTTP_201_CREATED)
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


@router.post("/flow", status_code=status.HTTP_201_CREATED)
async def ingest_flow(session: SessionDep, flow: FlowRecordIn) -> FlowRecordOut:
    """Ingest a single flow record. Useful for live producers and tests."""
    parsed = ParsedFlow.model_validate(flow.model_dump())
    event = await insert_single_flow(session, parsed)
    return FlowRecordOut.model_validate(event)


@router.get("/jobs")
async def list_jobs(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[IngestionJobOut]:
    result = await session.execute(
        select(IngestionJob).order_by(desc(IngestionJob.created_at)).limit(limit)
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
