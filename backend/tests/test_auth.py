"""Authentication & RBAC tests.

The auth layer is stateless (token claims), so most of this suite is DB-free:
password hashing, token round-trips, dependency-level role checks, and
endpoint-level 401/403 behavior. Login (the only DB-backed path) is exercised
with a stubbed ``user_service`` + an overridden DB session, so it runs anywhere.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.api.deps import (
    AuthPrincipal,
    db_session,
    enforce_rbac,
    get_current_user,
    require_admin,
    require_analyst,
    require_min_role,
    require_roles,
)
from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.security import (
    create_access_token,
    decode_access_token,
    get_password_hash,
    verify_password,
)
from app.models.enums import Role
from app.services import user_service

# ---------------------------------------------------------------------------
# Password hashing (pure).
# ---------------------------------------------------------------------------


def test_password_hash_is_not_plaintext_and_verifies() -> None:
    hashed = get_password_hash("Sup3r!secret")
    assert hashed != "Sup3r!secret"
    assert verify_password("Sup3r!secret", hashed)
    assert not verify_password("wrong-password", hashed)


def test_password_hash_is_salted_unique() -> None:
    assert get_password_hash("same") != get_password_hash("same")


def test_verify_password_tolerates_malformed_hash() -> None:
    assert verify_password("anything", "not-a-real-bcrypt-hash") is False


# ---------------------------------------------------------------------------
# JWT round-trip (pure).
# ---------------------------------------------------------------------------


def test_token_carries_subject_and_role() -> None:
    token, expires_at = create_access_token("alice", {"role": Role.ANALYST.value})
    claims = decode_access_token(token)
    assert claims is not None
    assert claims["sub"] == "alice"
    assert claims["role"] == "ANALYST"
    assert claims["exp"] > claims["iat"]
    assert expires_at.timestamp() == pytest.approx(claims["exp"], abs=1)


def test_decode_rejects_garbage_token() -> None:
    assert decode_access_token("not.a.jwt") is None


# ---------------------------------------------------------------------------
# get_current_user (pure dependency call).
# ---------------------------------------------------------------------------


async def test_get_current_user_rejects_missing_header() -> None:
    with pytest.raises(UnauthorizedError):
        await get_current_user(None)


async def test_get_current_user_rejects_non_bearer() -> None:
    with pytest.raises(UnauthorizedError):
        await get_current_user("Basic abc123")


async def test_get_current_user_rejects_invalid_token() -> None:
    with pytest.raises(UnauthorizedError):
        await get_current_user("Bearer garbage")


async def test_get_current_user_accepts_valid_token() -> None:
    token, _ = create_access_token("bob", {"role": Role.ADMIN.value})
    principal = await get_current_user(f"Bearer {token}")
    assert principal.username == "bob"
    assert principal.role == Role.ADMIN


async def test_get_current_user_rejects_unknown_role() -> None:
    token, _ = create_access_token("eve", {"role": "SUPERUSER"})
    with pytest.raises(UnauthorizedError):
        await get_current_user(f"Bearer {token}")


# ---------------------------------------------------------------------------
# Role guards (pure dependency calls).
# ---------------------------------------------------------------------------


async def test_require_roles_exact_membership() -> None:
    dep = require_roles(Role.ADMIN)
    admin = AuthPrincipal("a", Role.ADMIN)
    assert await dep(admin) is admin
    with pytest.raises(ForbiddenError):
        await dep(AuthPrincipal("b", Role.ANALYST))


async def test_require_min_role_is_rank_aware() -> None:
    dep = require_min_role(Role.ANALYST)
    assert (await dep(AuthPrincipal("a", Role.ADMIN))).role == Role.ADMIN
    assert (await dep(AuthPrincipal("b", Role.ANALYST))).role == Role.ANALYST
    with pytest.raises(ForbiddenError):
        await dep(AuthPrincipal("c", Role.VIEWER))


async def test_convenience_guards() -> None:
    with pytest.raises(ForbiddenError):
        await require_admin(AuthPrincipal("a", Role.ANALYST))
    with pytest.raises(ForbiddenError):
        await require_analyst(AuthPrincipal("v", Role.VIEWER))


@pytest.mark.parametrize(
    ("method", "role", "allowed"),
    [
        ("GET", Role.VIEWER, True),
        ("GET", Role.ANALYST, True),
        ("GET", Role.ADMIN, True),
        ("POST", Role.VIEWER, False),
        ("POST", Role.ANALYST, True),
        ("DELETE", Role.VIEWER, False),
        ("DELETE", Role.ADMIN, True),
    ],
)
async def test_enforce_rbac_method_policy(
    method: str, role: Role, allowed: bool
) -> None:
    request = SimpleNamespace(method=method)
    principal = AuthPrincipal("u", role)
    if allowed:
        assert await enforce_rbac(request, principal) is principal  # type: ignore[arg-type]
    else:
        with pytest.raises(ForbiddenError):
            await enforce_rbac(request, principal)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Endpoint-level enforcement (ASGI client, DB-free via short-circuit).
# ---------------------------------------------------------------------------


def _headers(role: Role, username: str = "tester") -> dict[str, str]:
    token, _ = create_access_token(username, {"role": role.value})
    return {"Authorization": f"Bearer {token}"}


async def test_protected_read_requires_token(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/alerts")
    assert resp.status_code == 401


async def test_protected_mutation_requires_token(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/response/recommend/1")
    assert resp.status_code == 401


async def test_viewer_blocked_from_mutation(client: AsyncClient) -> None:
    # Detection run is a mutation → VIEWER is forbidden before the handler runs.
    resp = await client.post(
        "/api/v1/detection/run", json={"limit": 10}, headers=_headers(Role.VIEWER)
    )
    assert resp.status_code == 403


async def test_me_returns_identity_for_each_role(client: AsyncClient) -> None:
    for role in (Role.VIEWER, Role.ANALYST, Role.ADMIN):
        resp = await client.get("/api/v1/auth/me", headers=_headers(role, "u-" + role.value))
        assert resp.status_code == 200
        body = resp.json()
        assert body["role"] == role.value
        assert body["username"] == "u-" + role.value


async def test_me_requires_token(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


async def test_health_stays_public(client: AsyncClient) -> None:
    assert (await client.get("/health")).status_code == 200


# ---------------------------------------------------------------------------
# Login (DB-backed path, stubbed).
# ---------------------------------------------------------------------------


async def _dummy_session() -> AsyncIterator[None]:
    yield None


async def test_login_success_issues_token(
    app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    app.dependency_overrides[db_session] = _dummy_session

    async def fake_auth(session, *, username: str, password: str):
        assert username == "alice" and password == "pw"
        return SimpleNamespace(username="alice", role=Role.ANALYST)

    monkeypatch.setattr(user_service, "authenticate", fake_auth)

    resp = await client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "pw"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["user"] == {"username": "alice", "role": "ANALYST"}
    claims = decode_access_token(body["access_token"])
    assert claims is not None and claims["sub"] == "alice" and claims["role"] == "ANALYST"

    app.dependency_overrides.clear()


async def test_login_failure_is_401(
    app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    app.dependency_overrides[db_session] = _dummy_session

    async def fake_auth(session, *, username: str, password: str):
        return None

    monkeypatch.setattr(user_service, "authenticate", fake_auth)

    resp = await client.post(
        "/api/v1/auth/login", json={"username": "x", "password": "y"}
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Admin-only user management.
# ---------------------------------------------------------------------------


async def test_create_user_forbidden_for_non_admin(client: AsyncClient) -> None:
    for role in (Role.VIEWER, Role.ANALYST):
        resp = await client.post(
            "/api/v1/auth/users",
            json={"username": "new", "password": "password123", "role": "VIEWER"},
            headers=_headers(role),
        )
        assert resp.status_code == 403


async def test_create_user_requires_auth(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/users",
        json={"username": "new", "password": "password123", "role": "VIEWER"},
    )
    assert resp.status_code == 401
