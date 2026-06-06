"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core import ratelimit
from app.main import create_app


@pytest.fixture(autouse=True)
def _isolate_rate_limiter() -> None:
    """Give every test a fresh in-process limiter so counters never leak.

    Without this the process-wide singleton would carry hits between tests and
    trip unrelated assertions.
    """
    ratelimit.get_policies.cache_clear()
    ratelimit.set_rate_limiter(ratelimit.InMemoryRateLimiter())


@pytest.fixture
def app() -> FastAPI:
    """A fresh app instance per test so dependency_overrides don't leak."""
    return create_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
