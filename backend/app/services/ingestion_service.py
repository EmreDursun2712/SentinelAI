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

from datetime import UTC, datetime, timedelta
from typing import Any, BinaryIO

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import EventType, publish_event
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

        await publish_event(
            EventType.INGESTION_JOB_COMPLETED,
            {
                "job_id": job_id,
                "total_rows": total,
                "valid_rows": valid,
                "invalid_rows": invalid,
            },
        )

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


async def insert_flow_batch(
    session: AsyncSession, flows: list[ParsedFlow], *, kind: IngestionKind = IngestionKind.STREAM
) -> int:
    """Bulk-insert a batch of pre-validated flows (e.g. from the live sensor).

    Records a lightweight STREAM ``IngestionJob`` for auditability, inserts the
    events, and commits. Returns the number of events inserted.
    """
    if not flows:
        return 0

    job = IngestionJob(
        kind=kind,
        source="sensor:batch",
        status=IngestionStatus.RUNNING,
        started_at=datetime.now(UTC),
    )
    session.add(job)
    await session.flush()
    job_id = job.id

    events = [_to_orm(f, job_id) for f in flows]
    session.add_all(events)
    await session.flush()

    await session.execute(
        update(IngestionJob)
        .where(IngestionJob.id == job_id)
        .values(
            status=IngestionStatus.COMPLETED,
            records_total=len(flows),
            records_done=len(flows),
            records_failed=0,
            completed_at=datetime.now(UTC),
        )
    )
    await session.commit()
    logger.info("ingestion.batch_inserted", job_id=job_id, count=len(events))
    await publish_event(
        EventType.INGESTION_JOB_COMPLETED,
        {"job_id": job_id, "total_rows": len(flows), "valid_rows": len(flows), "invalid_rows": 0},
    )
    return len(events)


async def sensor_status(session: AsyncSession, *, live_window_seconds: int) -> dict[str, Any]:
    """Ingest-activity summary used as a live-sensor liveness proxy.

    The backend doesn't run the sensor process, so 'live' means 'events arrived
    within the live window'. Reports last event time + recent counts.
    """
    now = datetime.now(UTC)
    since = now - timedelta(seconds=live_window_seconds)

    total = int((await session.execute(select(func.count(NetworkEvent.id)))).scalar_one() or 0)
    last_event_at = (
        await session.execute(select(func.max(NetworkEvent.created_at)))
    ).scalar_one_or_none()
    recent = int(
        (
            await session.execute(
                select(func.count(NetworkEvent.id)).where(NetworkEvent.created_at >= since)
            )
        ).scalar_one()
        or 0
    )
    return {
        "live": recent > 0,
        "last_event_at": last_event_at,
        "events_recent": recent,
        "total_events": total,
        "live_window_seconds": live_window_seconds,
    }


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
