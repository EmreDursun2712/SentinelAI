"""arq worker entrypoint.

Run with:  ``arq app.worker.WorkerSettings``  (see the ``worker`` compose service).

The worker shares the backend codebase and calls the same async services. On
startup it initializes the DB engine, loads the model (for detection/retrain),
and points the event broadcaster at Redis so task/domain events it publishes
reach WebSocket clients connected to the API workers.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

from app.core.broadcast import RedisBroadcaster, set_broadcaster
from app.core.config import get_settings
from app.core.db import dispose_engine, get_engine, init_engine
from app.core.logging import configure_logging, get_logger
from app.core.queue import arq_redis_settings
from app.core.tracing import setup_tracing
from app.services.model_registry import get_model_registry
from app.tasks.jobs import (
    daily_summary_task,
    detection_run_task,
    drift_run_task,
    ml_retrain_task,
    report_alert_task,
    retention_cleanup_task,
)

logger = get_logger("worker")

_settings = get_settings()
_REDIS_URL = _settings.redis_url or "redis://localhost:6379/0"


async def on_startup(ctx: dict) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    init_engine(settings.database_url)
    setup_tracing(None, settings, engine=get_engine())

    # Publish events to Redis so the API workers' subscribers fan them to clients.
    import redis.asyncio as aioredis

    client = aioredis.from_url(settings.redis_url or _REDIS_URL, decode_responses=True)
    set_broadcaster(RedisBroadcaster(client))
    ctx["redis_broadcast_client"] = client

    try:
        get_model_registry().load_from_disk(settings.ml_artifacts_dir)
    except Exception:
        logger.exception("worker.model_load_failed")

    logger.info("worker.startup", queue=settings.task_queue_name)


async def on_shutdown(ctx: dict) -> None:
    import contextlib

    client = ctx.get("redis_broadcast_client")
    if client is not None:
        with contextlib.suppress(Exception):
            await client.aclose()
    await dispose_engine()
    logger.info("worker.shutdown")


class WorkerSettings:
    """arq worker configuration (class attributes read by ``arq``)."""

    functions: ClassVar[list[Callable]] = [
        detection_run_task,
        report_alert_task,
        daily_summary_task,
        drift_run_task,
        retention_cleanup_task,
        ml_retrain_task,
    ]
    on_startup = on_startup
    on_shutdown = on_shutdown
    redis_settings = arq_redis_settings(_REDIS_URL)
    queue_name = _settings.task_queue_name
    max_jobs = 10
    job_timeout = 600  # 10 min — large detection batches / retrain
    health_check_interval = 30
