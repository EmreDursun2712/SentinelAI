"""Rate-limiting tests.

The Redis backend is exercised in deployment; here we test the policy parser,
the sliding-window math, keying, and the end-to-end 429 behavior using the
in-process limiter (installed for every test by the conftest fixture). That
keeps the suite deterministic and Redis-free.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.api.deps import client_ip, db_session, rate_limit_identity
from app.core.ratelimit import (
    InMemoryRateLimiter,
    NoopRateLimiter,
    Policy,
    get_policy,
    parse_rate,
)
from app.core.security import create_access_token
from app.models.enums import Role
from app.services import user_service

# ---------------------------------------------------------------------------
# Policy parsing.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("spec", "limit", "seconds"),
    [
        ("5/minute", 5, 60),
        ("120/min", 120, 60),
        ("10/second", 10, 1),
        ("20/hour", 20, 3600),
    ],
)
def test_parse_rate_valid(spec: str, limit: int, seconds: int) -> None:
    policy = parse_rate(spec)
    assert policy.limit == limit
    assert policy.window_seconds == seconds


@pytest.mark.parametrize("spec", ["5", "5/decade", "0/minute", "-3/minute", "abc/min"])
def test_parse_rate_invalid(spec: str) -> None:
    with pytest.raises(ValueError):
        parse_rate(spec)


def test_default_policies_match_spec() -> None:
    assert get_policy("login") == Policy(5, 60)
    assert get_policy("authenticated") == Policy(120, 60)
    assert get_policy("ingest") == Policy(10, 60)
    assert get_policy("detection") == Policy(5, 60)
    assert get_policy("report") == Policy(20, 60)
    assert get_policy("response") == Policy(60, 60)


def test_get_policy_unknown_raises() -> None:
    with pytest.raises(KeyError):
        get_policy("does-not-exist")


# ---------------------------------------------------------------------------
# Sliding window math (in-memory, injected clock).
# ---------------------------------------------------------------------------


async def test_inmemory_sliding_window_trips_and_recovers() -> None:
    clock = {"t": 1000.0}
    rl = InMemoryRateLimiter(now=lambda: clock["t"])
    policy = Policy(limit=2, window_seconds=10)

    r1 = await rl.hit("k", policy)
    r2 = await rl.hit("k", policy)
    assert r1.allowed and r2.allowed
    assert r2.remaining == 0

    blocked = await rl.hit("k", policy)
    assert not blocked.allowed
    assert blocked.retry_after >= 1

    # Advance past the window — the oldest hits fall out and we're allowed again.
    clock["t"] += 11
    assert (await rl.hit("k", policy)).allowed


async def test_inmemory_buckets_are_independent_per_key() -> None:
    rl = InMemoryRateLimiter()
    policy = Policy(limit=1, window_seconds=60)
    assert (await rl.hit("rl:x:user:a", policy)).allowed
    assert not (await rl.hit("rl:x:user:a", policy)).allowed
    # Different identity → independent budget.
    assert (await rl.hit("rl:x:user:b", policy)).allowed


async def test_noop_limiter_always_allows() -> None:
    rl = NoopRateLimiter()
    policy = Policy(limit=1, window_seconds=60)
    for _ in range(5):
        assert (await rl.hit("k", policy)).allowed


# ---------------------------------------------------------------------------
# Keying helpers.
# ---------------------------------------------------------------------------


def test_rate_limit_identity_prefers_user_then_ip() -> None:
    user = SimpleNamespace(username="alice", role=Role.ANALYST)
    assert rate_limit_identity(user, "9.9.9.9") == "user:alice"  # type: ignore[arg-type]
    assert rate_limit_identity(None, "9.9.9.9") == "ip:9.9.9.9"


def test_client_ip_prefers_forwarded_for() -> None:
    req = SimpleNamespace(
        headers={"x-forwarded-for": "203.0.113.7, 10.0.0.1"},
        client=SimpleNamespace(host="10.0.0.1"),
    )
    assert client_ip(req) == "203.0.113.7"  # type: ignore[arg-type]


def test_client_ip_falls_back_to_peer_then_unknown() -> None:
    with_peer = SimpleNamespace(headers={}, client=SimpleNamespace(host="192.0.2.5"))
    assert client_ip(with_peer) == "192.0.2.5"  # type: ignore[arg-type]
    no_peer = SimpleNamespace(headers={}, client=None)
    assert client_ip(no_peer) == "unknown"  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# End-to-end 429 behavior.
# ---------------------------------------------------------------------------


async def _dummy_session() -> AsyncIterator[None]:
    yield None


def _headers(role: Role) -> dict[str, str]:
    token, _ = create_access_token("limited-user", {"role": role.value})
    return {"Authorization": f"Bearer {token}"}


async def test_login_brute_force_trips_429(
    app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    app.dependency_overrides[db_session] = _dummy_session

    async def fake_auth(session, *, username: str, password: str):
        return None  # always "wrong password" so we isolate the rate limiter

    monkeypatch.setattr(user_service, "authenticate", fake_auth)

    body = {"username": "victim", "password": "guess"}
    # Default login policy is 5/minute (per IP+username).
    for _ in range(5):
        assert (await client.post("/api/v1/auth/login", json=body)).status_code == 401

    blocked = await client.post("/api/v1/auth/login", json=body)
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert "retry-after" in {k.lower() for k in blocked.headers}

    app.dependency_overrides.clear()


async def test_authenticated_expensive_endpoint_is_limited(client: AsyncClient) -> None:
    # Detection is 5/minute per user. The rate-limit dependency runs before the
    # handler, so the 6th call is rejected regardless of model state. /predict
    # takes no DB session, keeping this test self-contained.
    headers = _headers(Role.ANALYST)
    body = {
        "flows": [
            {
                "event_time": "2026-01-01T00:00:00Z",
                "src_ip": "10.0.0.1",
                "dst_ip": "10.0.0.2",
                "features": {},
            }
        ]
    }
    statuses = [
        (await client.post("/api/v1/detection/predict", json=body, headers=headers)).status_code
        for _ in range(6)
    ]
    assert statuses[-1] == 429
    assert 429 not in statuses[:5]


async def test_login_limit_is_per_username(
    app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    app.dependency_overrides[db_session] = _dummy_session

    async def fake_auth(session, *, username: str, password: str):
        return None

    monkeypatch.setattr(user_service, "authenticate", fake_auth)

    for _ in range(5):
        await client.post("/api/v1/auth/login", json={"username": "alice", "password": "x"})
    # alice is now rate-limited...
    assert (
        await client.post("/api/v1/auth/login", json={"username": "alice", "password": "x"})
    ).status_code == 429
    # ...but a different username (same IP) still has budget.
    assert (
        await client.post("/api/v1/auth/login", json={"username": "bob", "password": "x"})
    ).status_code == 401

    app.dependency_overrides.clear()
