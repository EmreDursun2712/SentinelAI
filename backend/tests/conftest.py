"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_active_principal, get_current_user
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
    """A fresh app instance per test so dependency_overrides don't leak.

    By default we override the DB-backed active-user check with the claims-only
    ``get_current_user`` so endpoint tests stay DB-free (the protected routers
    never touch Postgres just to validate a token). The real check is covered
    directly in ``test_auth.py`` and end-to-end in ``tests/integration``.
    """
    application = create_app()
    application.dependency_overrides[get_active_principal] = get_current_user
    return application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    # https base URL so httpx stores the Secure auth cookies the app sets.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as ac:
        yield ac
