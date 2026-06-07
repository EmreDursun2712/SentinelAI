"""Rate limiting — Redis-backed sliding window with an in-process fallback.

Design
------
* A small :class:`RateLimiter` interface with three implementations:
  - :class:`RedisRateLimiter`  — atomic sliding-window log via a Lua script
    (the production backend; shared across processes/replicas).
  - :class:`InMemoryRateLimiter` — per-process sliding window (dev fallback +
    deterministic tests). Not safe across multiple workers.
  - :class:`NoopRateLimiter` — used when rate limiting is disabled.
* Named **policies** (login, ingest, detection, …) parsed from settings as
  ``"<count>/<unit>"`` strings, so limits are env-overridable without code.
* A process-wide singleton chosen at startup (see ``app.main`` lifespan). It
  lazily defaults to the in-memory limiter so unit tests and ``--reload`` work
  without an explicit init step.

Runtime Redis errors fail **open** (allow + warn): the limiter must never become
a single point of failure for the whole API. Startup, by contrast, fails
**closed** in production (the app refuses to boot without a reachable Redis).
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Policies.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Policy:
    limit: int
    window_seconds: int


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int  # seconds until the caller may retry (0 when allowed)


_UNIT_SECONDS = {
    "second": 1,
    "sec": 1,
    "s": 1,
    "minute": 60,
    "min": 60,
    "m": 60,
    "hour": 3600,
    "hr": 3600,
    "h": 3600,
}


def parse_rate(spec: str) -> Policy:
    """Parse a ``"<count>/<unit>"`` spec, e.g. ``"5/minute"`` → Policy(5, 60)."""
    count_str, sep, unit = spec.partition("/")
    if not sep:
        raise ValueError(f"Invalid rate spec {spec!r}; expected '<count>/<unit>'.")
    unit_key = unit.strip().lower()
    if unit_key not in _UNIT_SECONDS:
        raise ValueError(f"Unknown rate unit {unit!r} in {spec!r}.")
    count = int(count_str.strip())
    if count <= 0:
        raise ValueError(f"Rate count must be positive in {spec!r}.")
    return Policy(limit=count, window_seconds=_UNIT_SECONDS[unit_key])


@lru_cache(maxsize=1)
def get_policies() -> dict[str, Policy]:
    s = get_settings()
    return {
        "login": parse_rate(s.rate_limit_login),
        "authenticated": parse_rate(s.rate_limit_authenticated),
        "ingest": parse_rate(s.rate_limit_ingest),
        "detection": parse_rate(s.rate_limit_detection),
        "report": parse_rate(s.rate_limit_report),
        "response": parse_rate(s.rate_limit_response),
    }


def get_policy(name: str) -> Policy:
    policies = get_policies()
    try:
        return policies[name]
    except KeyError as exc:
        raise KeyError(f"Unknown rate-limit policy {name!r}.") from exc


# ---------------------------------------------------------------------------
# Limiter implementations.
# ---------------------------------------------------------------------------


class RateLimiter(Protocol):
    backend: str

    async def hit(self, key: str, policy: Policy) -> RateLimitResult: ...

    async def aclose(self) -> None: ...


class NoopRateLimiter:
    """Always allows. Used when rate limiting is disabled."""

    backend = "noop"

    async def hit(self, key: str, policy: Policy) -> RateLimitResult:
        return RateLimitResult(True, policy.limit, policy.limit, 0)

    async def aclose(self) -> None:
        return None


class InMemoryRateLimiter:
    """Per-process sliding-window log. Deterministic via an injectable clock."""

    backend = "memory"

    def __init__(self, now=time.monotonic) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()
        self._now = now

    async def hit(self, key: str, policy: Policy) -> RateLimitResult:
        async with self._lock:
            now = self._now()
            cutoff = now - policy.window_seconds
            dq = self._hits[key]
            while dq and dq[0] <= cutoff:
                dq.popleft()
            if len(dq) < policy.limit:
                dq.append(now)
                return RateLimitResult(True, policy.limit, policy.limit - len(dq), 0)
            retry = max(1, math.ceil(dq[0] + policy.window_seconds - now))
            return RateLimitResult(False, policy.limit, 0, retry)

    async def aclose(self) -> None:
        self._hits.clear()


# Atomic sliding-window log. Trims expired members, counts, and conditionally
# records the new hit — all in one round trip so concurrent callers can't race
# past the limit. Returns {allowed, remaining, retry_after_seconds}.
_REDIS_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local count = redis.call('ZCARD', key)
if count < limit then
  redis.call('ZADD', key, now, member)
  redis.call('PEXPIRE', key, window)
  return {1, limit - count - 1, 0}
end
local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
local retry = 1
if oldest[2] then
  retry = math.ceil((tonumber(oldest[2]) + window - now) / 1000)
  if retry < 1 then retry = 1 end
end
redis.call('PEXPIRE', key, window)
return {0, 0, retry}
"""


class RedisRateLimiter:
    """Shared sliding-window limiter backed by Redis (redis.asyncio client)."""

    backend = "redis"

    def __init__(self, client) -> None:
        self._client = client

    async def hit(self, key: str, policy: Policy) -> RateLimitResult:
        now_ms = int(time.time() * 1000)
        window_ms = policy.window_seconds * 1000
        member = f"{now_ms}-{secrets.token_hex(6)}"
        try:
            res = await self._client.eval(
                _REDIS_LUA, 1, key, now_ms, window_ms, policy.limit, member
            )
        except Exception as exc:  # connection blip, etc. — fail open + warn.
            logger.warning("ratelimit.redis_error", key=key, error=str(exc))
            return RateLimitResult(True, policy.limit, policy.limit, 0)
        allowed, remaining, retry = int(res[0]), int(res[1]), int(res[2])
        return RateLimitResult(bool(allowed), policy.limit, remaining, retry)

    async def aclose(self) -> None:
        with contextlib.suppress(Exception):  # best effort on shutdown
            await self._client.aclose()


# ---------------------------------------------------------------------------
# Process-wide singleton.
# ---------------------------------------------------------------------------


_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    """Return the active limiter, lazily defaulting to in-memory.

    The lazy default keeps unit tests and ``uvicorn --reload`` workers working
    without an explicit init; ``app.main`` overrides it at startup with the
    backend chosen from settings.
    """
    global _limiter
    if _limiter is None:
        _limiter = InMemoryRateLimiter()
    return _limiter


def set_rate_limiter(limiter: RateLimiter) -> None:
    global _limiter
    _limiter = limiter
