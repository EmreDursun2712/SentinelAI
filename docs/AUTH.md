# Authentication & RBAC

SentinelAI uses **stateless JWT** auth with **role-based access control**. Every
`/api/v1` endpoint requires a bearer token except `POST /api/v1/auth/login`;
`/health`, `/readyz`, `/docs`, `/redoc`, and `/api/v1/openapi.json` stay public.

## Roles

`VIEWER < ANALYST < ADMIN` (a higher role satisfies any lower requirement).

| Role | Can |
| --- | --- |
| `VIEWER` | Read everything (dashboards, alerts, reports, drift, model). |
| `ANALYST` | All reads + SOC mutations (triage, investigate, report, respond, approve/reject/rollback, run detection/drift, ingest). |
| `ADMIN` | Everything + user management (`POST /auth/users`). |

## Authorization model (method-based RBAC)

Authorization is enforced by a single dependency applied to every functional
router: **reads** (`GET`/`HEAD`/`OPTIONS`) need `VIEWER+`, **mutations**
(`POST`/`PUT`/`PATCH`/`DELETE`) need `ANALYST+`. Admin-only endpoints add an
explicit `require_admin` dependency. Unauthenticated → `401`; authenticated but
under-privileged → `403`.

Per-request auth is **claims-based** (the token carries `sub` + `role`), so the
hot path never hits the DB. The `users` table is consulted only at login (which
checks the bcrypt password and `is_active`) and at admin user creation. Tokens
are short-lived (`SENTINEL_JWT_TTL_MINUTES`, default 12h); a deactivated user
keeps access until their current token expires — an accepted trade-off for this
project's scope.

## Endpoints

| Method | Path | Role | Purpose |
| --- | --- | --- | --- |
| POST | `/api/v1/auth/login` | public | Exchange username/password for a JWT. |
| GET | `/api/v1/auth/me` | any | Current identity from the token. |
| POST | `/api/v1/auth/logout` | any | Stateless no-op (client discards token). |
| POST | `/api/v1/auth/users` | ADMIN | Create a user `{username, password, role}`. |

```bash
TOKEN=$(curl -fsS localhost:8000/api/v1/auth/login -H 'content-type: application/json' \
  -d '{"username":"admin","password":"<pw>"}' | jq -r .access_token)
curl -fsS localhost:8000/api/v1/alerts -H "Authorization: Bearer $TOKEN"
```

## Bootstrap admin (no hardcoded users)

The first admin is created on startup **only** when both env vars are set; if
either is missing, no default user is ever created:

```
SENTINEL_BOOTSTRAP_ADMIN_USERNAME=admin
SENTINEL_BOOTSTRAP_ADMIN_PASSWORD=<a-strong-password>
```

Bootstrap is create-only — it never overwrites an existing user's password.

## Configuration & secret rotation

| Env | Default | Notes |
| --- | --- | --- |
| `SENTINEL_JWT_SECRET` | `dev-jwt-secret-change-me` | **Rotate before any shared deploy.** |
| `SENTINEL_JWT_ALGORITHM` | `HS256` | |
| `SENTINEL_JWT_TTL_MINUTES` | `720` | Token lifetime. |
| `SENTINEL_API_KEY` | `dev-api-key-change-me` | Service-to-service guard (kept for non-interactive callers). |

The backend **refuses to start** in a production-like `SENTINEL_ENV`
(`production`/`prod`/`staging`) while `JWT_SECRET` is still the shipped default.

## Frontend

`AuthProvider` stores the token in `localStorage` (XSS-aware: single namespaced
key, never logged/rendered), attaches `Authorization: Bearer` to every request,
redirects to `/login` on `401`, and surfaces `403` to the caller. The Topbar
shows the signed-in user + role and a sign-out button.

Tests: `backend/tests/test_auth.py` (hashing, tokens, RBAC, login, 401/403);
`frontend/src/lib/auth/*.test.{ts,tsx}`.
