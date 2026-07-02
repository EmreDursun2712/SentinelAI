"""Admin endpoints: auth + demo-reset gating (no DB needed for these paths)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token
from app.models.enums import Role


def _auth_header(role: Role, username: str = "admin-test") -> dict[str, str]:
    token, _ = create_access_token(username, {"role": role.value})
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_reset_demo_requires_auth(client: AsyncClient) -> None:
    # A 401 (not 404) proves the route exists and is wired behind auth.
    response = await client.post("/api/v1/admin/reset-demo")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_reset_demo_forbidden_for_non_admin(client: AsyncClient) -> None:
    response = await client.post("/api/v1/admin/reset-demo", headers=_auth_header(Role.ANALYST))
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_reset_demo_404_when_disabled(client: AsyncClient) -> None:
    # Default config keeps the feature off, so even an ADMIN gets a 404 — the
    # endpoint is invisible and inert outside an explicitly enabled demo.
    response = await client.post("/api/v1/admin/reset-demo", headers=_auth_header(Role.ADMIN))
    assert response.status_code == 404
