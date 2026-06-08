"""Task-queue abstraction over arq (Redis-backed).

The API enqueues jobs; the arq worker (``app.worker``) runs them. A thin
:class:`TaskQueue` indirection keeps the rest of the app decoupled from arq and
makes enqueue trivially testable:

* :class:`ArqTaskQueue` — wraps an arq Redis pool and enqueues real jobs.
* :class:`NullTaskQueue` — no-op (used in dev without a worker, and in tests):
  the DB ``Task`` row is still created (PENDING) so the API behaves consistently;
  nothing runs until a real worker + Redis are present.

The active queue is chosen at startup (``app.main`` lifespan); tests get the lazy
Null default or inject a fake.
"""

from __future__ import annotations

from typing import Any, Protocol

from app.core.logging import get_logger

logger = get_logger(__name__)


def arq_redis_settings(redis_url: str):
    """Build arq ``RedisSettings`` from a redis DSN."""
    from arq.connections import RedisSettings

    return RedisSettings.from_dsn(redis_url)


class TaskQueue(Protocol):
    backend: str

    async def enqueue(self, function: str, *args: Any, **kwargs: Any) -> str | None: ...

    async def ping(self) -> bool: ...

    async def aclose(self) -> None: ...


class NullTaskQueue:
    """No-op queue. Enqueue returns None; the DB Task row stays PENDING."""

    backend = "null"

    async def enqueue(self, function: str, *args: Any, **kwargs: Any) -> str | None:
        logger.warning("queue.enqueue_noop", function=function)
        return None

    async def ping(self) -> bool:
        return False

    async def aclose(self) -> None:
        return None


class ArqTaskQueue:
    """Enqueues jobs onto a real arq Redis pool."""

    backend = "arq"

    def __init__(self, pool, queue_name: str) -> None:
        self._pool = pool
        self._queue_name = queue_name

    async def enqueue(self, function: str, *args: Any, **kwargs: Any) -> str | None:
        job = await self._pool.enqueue_job(function, *args, _queue_name=self._queue_name, **kwargs)
        return job.job_id if job is not None else None

    async def ping(self) -> bool:
        try:
            await self._pool.ping()
            return True
        except Exception as exc:
            logger.warning("queue.redis_ping_failed", error=str(exc))
            return False

    async def aclose(self) -> None:
        import contextlib

        with contextlib.suppress(Exception):
            await self._pool.aclose()


_queue: TaskQueue | None = None


def get_task_queue() -> TaskQueue:
    global _queue
    if _queue is None:
        _queue = NullTaskQueue()
    return _queue


def set_task_queue(queue: TaskQueue) -> None:
    global _queue
    _queue = queue
