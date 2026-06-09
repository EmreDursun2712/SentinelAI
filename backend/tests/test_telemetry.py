"""Client-error telemetry endpoint — public, best-effort, no DB."""

from __future__ import annotations

from httpx import AsyncClient


async def test_client_error_accepts_report(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/telemetry/client-error",
        json={
            "message": "Cannot read properties of undefined",
            "stack": "Error: boom\n  at Foo",
            "component_stack": "in Dashboard",
            "url": "https://app/local/dashboard",
        },
    )
    assert resp.status_code == 204


async def test_client_error_is_public_no_auth_required(client: AsyncClient) -> None:
    # No Authorization header at all — must still accept (errors happen pre-login).
    resp = await client.post("/api/v1/telemetry/client-error", json={"message": "anonymous boom"})
    assert resp.status_code == 204


async def test_client_error_validates_message_required(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/telemetry/client-error", json={})
    assert resp.status_code == 422
