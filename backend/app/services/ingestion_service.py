"""Ingestion orchestration: drive the ``IngestionJob`` lifecycle and bulk-insert events.

Flow:

    1. Insert an ``IngestionJob`` row (status=RUNNING) and commit so the row
       survives any later failure.
    2. Stream the CSV row-by-row, batching valid ``NetworkEvent`` inserts.
    3. On clean completion, update the job to COMPLETED with totals.
    4. On unexpected failure, roll back uncommitted inserts and update the job
       to FAILED with the error message. The job row itself is preserved.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import BinaryIO

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.ingestion.csv_loader import stream_csv
from app.ingestion.parser import ParsedFlow
from app.models import IngestionJob, NetworkEvent
from app.models.enums import IngestionKind, IngestionStatus
from app.schemas.ingestion import IngestionSummary, RowErrorOut

logger = get_logger(__name__)

MAX_ERRORS_RETURNED = 50
BATCH_SIZE = 500


async def ingest_csv(
    session: AsyncSession,
    *,
    file: BinaryIO,
    source: str,
    kind: IngestionKind = IngestionKind.REPLAY,
    rate_limit: int | None = None,
) -> IngestionSummary:
    """Drive an ingestion job from a binary CSV file-like object."""
    job = IngestionJob(
        kind=kind,
        source=source,
        status=IngestionStatus.RUNNING,
        rate_limit=rate_limit,
        started_at=datetime.now(UTC),
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    job_id = job.id

    log = logger.bind(job_id=job_id, source=source)
    log.info("ingestion.started")

    total = 0
    invalid = 0
    errors: list[RowErrorOut] = []
    errors_truncated = False
    batch: list[NetworkEvent] = []

    try:
        for result in stream_csv(file):
            total += 1
            if not result.ok:
                invalid += 1
                if len(errors) < MAX_ERRORS_RETURNED:
                    errors.append(
                        RowErrorOut(row_number=result.row_number, message=result.error or "")
                    )
                else:
                    errors_truncated = True
                continue

            assert result.parsed is not None
            batch.append(_to_orm(result.parsed, job_id))
            if len(batch) >= BATCH_SIZE:
                session.add_all(batch)
                await session.flush()
                batch.clear()

        if batch:
            session.add_all(batch)
            await session.flush()

        valid = total - invalid
        await session.execute(
            update(IngestionJob)
            .where(IngestionJob.id == job_id)
            .values(
                status=IngestionStatus.COMPLETED,
                records_total=total,
                records_done=valid,
                records_failed=invalid,
                completed_at=datetime.now(UTC),
            )
        )
        await session.commit()
        log.info("ingestion.completed", total=total, valid=valid, invalid=invalid)

        return IngestionSummary(
            job_id=job_id,
            status=IngestionStatus.COMPLETED,
            source=source,
            total_rows=total,
            valid_rows=valid,
            invalid_rows=invalid,
            errors=errors,
            errors_truncated=errors_truncated,
        )

    except Exception as exc:
        await session.rollback()
        message = str(exc)[:500] or exc.__class__.__name__
        await session.execute(
            update(IngestionJob)
            .where(IngestionJob.id == job_id)
            .values(
                status=IngestionStatus.FAILED,
                error_message=message,
                completed_at=datetime.now(UTC),
            )
        )
        await session.commit()
        log.exception("ingestion.failed", error=message)
        raise


async def insert_single_flow(session: AsyncSession, flow_in: ParsedFlow) -> NetworkEvent:
    """Persist a single flow record outside of an ingestion job."""
    event = _to_orm(flow_in, job_id=None)
    session.add(event)
    await session.commit()
    await session.refresh(event)
    return event


def _to_orm(parsed: ParsedFlow, job_id: int | None) -> NetworkEvent:
    return NetworkEvent(
        ingestion_job_id=job_id,
        event_time=parsed.event_time,
        src_ip=parsed.src_ip,
        dst_ip=parsed.dst_ip,
        src_port=parsed.src_port,
        dst_port=parsed.dst_port,
        protocol=parsed.protocol,
        label=parsed.label,
        features=parsed.features,
    )
