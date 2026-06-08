# Authentication & RBAC

SentinelAI uses **short-lived access tokens + long-lived refresh-token sessions**
with cookie-based auth, server-side revocation, and **role-based access control**.
Every `/api/v1` endpoint requires authentication except `POST /api/v1/auth/login`
and `POST /api/v1/auth/refresh`; `/health`, `/readyz`, `/docs`, `/redoc`, and
`/api/v1/openapi.json` stay public.

## Token model

| Token | Lifetime | Where it lives | Purpose |
| --- | --- | --- | --- |
| **Access** (JWT) | 15 min (`SENTINEL_ACCESS_TOKEN_TTL_MINUTES`) | Returned in the login/refresh **body**; the SPA holds it **in memory** and sends it as `Authorization: Bearer`. Also accepted from a `sentinelai_access` cookie. | Per-request auth. Carries `sub`, `role`, `ver`. |
| **Refresh** (opaque random) | 7 days (`SENTINEL_REFRESH_TOKEN_TTL_DAYS`) | **httpOnly** `sentinelai_refresh` cookie (JS can't read it), scoped to `/api/v1/auth`. | Mint new access tokens; the unit of revocation. |
| **CSRF** | = refresh lifetime | Readable `sentinelai_csrf` cookie. | Double-submit CSRF token. |

Refresh tokens are stored **hashed** (SHA-256) in `auth_sessions` — one row per
session — so a database leak never exposes a usable token. A session is valid
while `revoked_at IS NULL` and `expires_at` is in the future.

`token_version` (on `users`, mirrored in the access token's `ver` claim) is
bumped to invalidate **every** outstanding access token for a user at once
(logout-all, deactivation).

## Endpoints

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| POST | `/api/v1/auth/login` | public | Credentials → access token (body) + refresh & CSRF cookies. |
| POST | `/api/v1/auth/refresh` | refresh cookie + CSRF | Rotate the refresh token, mint a new access token. |
| POST | `/api/v1/auth/logout` | refresh cookie | Revoke the current session, clear cookies. |
| POST | `/api/v1/auth/logout-all` | access token | Revoke all sessions + bump `token_version` (all devices). |
| GET | `/api/v1/auth/me` | access token | Current identity (enforces `is_active`). |
| POST | `/api/v1/auth/users` | ADMIN | Create a user `{username, password, role}`. |
| POST | `/api/v1/auth/users/{username}/deactivate` | ADMIN | Deactivate: lock login, revoke sessions, invalidate tokens. |

### Refresh-token rotation

Every `/refresh` **rotates**: the presented token is revoked and a brand-new one
is issued. If an already-revoked token is presented again (a signal it leaked),
the user's **entire session family is revoked** and the call fails — forcing a
fresh login. The frontend's API client performs an automatic, single-flight
refresh on a `401`, then replays the original request once.

## Cookies, SameSite & CSRF

- **httpOnly Secure SameSite** cookies hold the refresh token; JS never sees it.
- **CSRF (double-submit):** the readable `sentinelai_csrf` cookie must be echoed
  in an `X-CSRF-Token` header on **unsafe** methods (`POST/PUT/PATCH/DELETE`) for
  any **cookie-authenticated** request. Header (Bearer) requests are exempt —
  they can't be forged cross-site. In practice this gates `/auth/refresh`;
  `/auth/login`, `/auth/logout`, and `/auth/logout-all` are exempt so they always
  work. Enforced by `CsrfMiddleware`; mismatch → `403 csrf_failed`.
- SameSite already blocks most cross-site cookie sends; the double-submit token
  is defense-in-depth and the primary protection when cookies are configured
  `SameSite=None` (a cross-site frontend deployment).

> **Localhost dev caveat.** Browsers silently drop `Secure` cookies over plain
> `http://localhost`. For non-HTTPS dev set **`SENTINEL_AUTH_COOKIE_SECURE=false`**
> (Docker Compose already does). Production keeps the secure default (`true`).
> Frontend (`:5173`) and API (`:8000`) are the same *site* (`localhost`), so the
> default `SameSite=lax` cookies are sent cross-origin in dev. A truly cross-site
> deployment needs `SENTINEL_AUTH_COOKIE_SAMESITE=none` (which requires `secure=true`).

## Authorization model (method-based RBAC)

`VIEWER < ANALYST < ADMIN` (a higher role satisfies any lower requirement).

| Role | Can |
| --- | --- |
| `VIEWER` | Read everything (dashboards, alerts, reports, drift, model). |
| `ANALYST` | All reads + SOC mutations (triage, investigate, report, respond, approve/reject/rollback, run detection/drift, ingest). |
| `ADMIN` | Everything + user management. |

A single dependency on every functional router enforces: **reads**
(`GET/HEAD/OPTIONS`) need `VIEWER+`, **mutations** need `ANALYST+`; admin-only
endpoints add `require_admin`. Unauthenticated → `401`; under-privileged → `403`.

**Per-request enforcement is DB-backed** (`get_active_principal`): every
protected request re-checks the account is still **active** and the token's `ver`
still matches the live `token_version`. So a deactivated user — or one logged out
everywhere — loses access **immediately**, not at token expiry. (Identity-only
paths like rate-limit keying and WebSocket auth use the cheaper claims-only
`get_current_user`.)

```bash
# Cookie flow (jar persists the httpOnly refresh + CSRF cookies):
curl -fsS -c jar -b jar localhost:8000/api/v1/auth/login \
  -H 'content-type: application/json' -d '{"username":"admin","password":"<pw>"}'
# → body has access_token; jar has sentinelai_refresh + sentinelai_csrf
curl -fsS -b jar localhost:8000/api/v1/alerts -H "Authorization: Bearer <access_token>"
```

## Bootstrap admin (no hardcoded users)

The first admin is created on startup **only** when both env vars are set; if
either is missing, no default user is ever created. Bootstrap is create-only —
it never overwrites an existing user's password.

```
SENTINEL_BOOTSTRAP_ADMIN_USERNAME=admin
SENTINEL_BOOTSTRAP_ADMIN_PASSWORD=<a-strong-password>
```

## Configuration

| Env | Default | Notes |
| --- | --- | --- |
| `SENTINEL_JWT_SECRET` | `dev-jwt-secret-change-me` | **Rotate before any shared deploy.** App refuses to start in prod with the default. |
| `SENTINEL_JWT_ALGORITHM` | `HS256` | |
| `SENTINEL_ACCESS_TOKEN_TTL_MINUTES` | `15` | Access-token lifetime. |
| `SENTINEL_REFRESH_TOKEN_TTL_DAYS` | `7` | Refresh-session lifetime. |
| `SENTINEL_AUTH_COOKIE_SECURE` | `true` | **Set `false` for http://localhost dev.** |
| `SENTINEL_AUTH_COOKIE_SAMESITE` | `lax` | `lax`/`strict`/`none` (`none` ⇒ must be secure). |
| `SENTINEL_AUTH_COOKIE_DOMAIN` | _(host-only)_ | Set for a shared parent domain if needed. |
| `SENTINEL_API_KEY` | `dev-api-key-change-me` | Service-to-service guard (non-interactive callers). |

## Frontend

No token is ever in `localStorage`. The access token lives **in memory only**;
the durable session is the httpOnly refresh cookie. On load the app calls
`/auth/me` — with no in-memory token the API client first calls `/auth/refresh`
(using the cookie), so the session is restored across reloads without storage.
The client attaches `Authorization: Bearer`, sends `credentials: "include"`, adds
`X-CSRF-Token` on unsafe methods, and on a `401` refreshes once then replays;
a failed refresh clears state and redirects to `/login`. "Sign out" revokes the
current session; "sign out everywhere" (`logoutAll`) revokes all of them.

## Tests

- `backend/tests/test_auth.py` — hashing, JWT round-trip, RBAC, login cookies,
  refresh CSRF + rotation, logout/logout-all, `get_active_principal` (active /
  inactive / version mismatch), deactivated-user rejection.
- `backend/tests/integration/test_auth_sessions.py` — real-Postgres session
  lifecycle: hashed storage, rotation, expiry, reuse-detection, revoke-all,
  deactivation lock-out.
- `frontend/src/lib/auth/*.test.{ts,tsx}`, `frontend/src/lib/api/client.test.ts`
  — in-memory token, CSRF cookie read, refresh-on-401 replay, AuthContext flows.
