# Production-Grade Hardening — Implementation Map

Audit-only document. **No application code is changed in this etap.** It maps
each known gap to the exact files, migrations, tests, and risks involved, and
fixes the safest implementation order.

Repo facts the plan relies on:

- Backend: FastAPI, SQLAlchemy 2 async, Alembic. Migration head = `0004_response_action_types`.
- Settings: `app/core/config.py` (pydantic-settings, env prefix `SENTINEL_`). Already
  carries `api_key`, `jwt_secret`, `jwt_algorithm`, `jwt_ttl_minutes` — **unused today**.
- Auth helpers exist (`app/core/security.py`, `app/api/deps.py::require_api_key`) but are
  **wired to no router** (`grep` confirms no `Depends(require_api_key)` / `dependencies=`).
- In-process event bus (`app/core/events.py`); **no service publishes to it**.
- WebSocket `/stream` only echoes (`app/api/routers/stream.py`).
- Frontend fetch client (`frontend/src/lib/api/client.ts`) sends **no auth header**;
  `useStream` (`frontend/src/lib/ws.ts`) is exported but unused.
- Ethics guardrails: DB `CHECK (simulated = TRUE)` (`ck_response_actions_simulated_only`)
  + `ResponseAgent.simulated_only = True` + `docs/ETHICS.md` rules #1 and #3.
- Tests: `pytest` (mostly pure, no DB) + `vitest` + `tsc --noEmit` + `ruff`.
  `conftest.py` has only an ASGI `client` fixture — **no DB / no auth fixture yet**.

Global commands (run from each subdir):

```bash
# backend/
ruff check . && ruff format --check . && pytest
# frontend/
npm test && npm run typecheck
# whole repo
make test && make lint && make typecheck
# e2e (needs running stack: make up)
bash infra/scripts/smoke_demo.sh
```

---

## Recommended order (safest first, ethics-critical last)

1. **AuthN/AuthZ (RBAC)** — foundation; rate-limit, WS auth, and real-response all gate on identity.
2. **Rate limiting** — isolated, low risk.
3. **WebSocket real broadcasting** — depends on WS auth from etap 1.
4. **Model drift tracking** — isolated backend + dashboard.
5. **Live capture sensor** — opt-in, disabled by default; **rewrites ETHICS rule #3**.
6. **Lab-only real-response** — highest risk, **rewrites ETHICS rule #1 + DB CHECK**; ships last.

---

## Etap 1 — Authentication & RBAC

**Approach (most secure):** users table + bcrypt (`passlib[bcrypt]` already a dep) + JWT
with a `role` claim. Roles: `VIEWER` (read), `ANALYST` (triage/respond/approve),
`ADMIN` (users + dangerous features). Keep `require_api_key` for service-to-service calls.

New:
- `backend/app/models/user.py` — User(id, username, email, hashed_password, role, is_active, created_at)
- `backend/app/schemas/auth.py` — LoginRequest, TokenOut, UserOut, CreateUserRequest
- `backend/app/services/user_service.py` — create_user, authenticate, get_by_username
- `backend/app/api/routers/auth.py` — `POST /auth/login`, `GET /auth/me`, `POST /auth/users` (ADMIN)
- `backend/migrations/versions/0005_users_and_roles.py` (down_revision `0004_response_action_types`)
- `frontend/src/lib/api/auth.ts`, `frontend/src/pages/LoginPage.tsx`, `frontend/src/lib/auth/` (context + ProtectedRoute)
- `backend/tests/test_auth.py`

Modify:
- `backend/app/models/enums.py` — add `Role` enum
- `backend/app/models/__init__.py` — register `User`
- `backend/app/core/security.py` — `get_password_hash` / `verify_password`
- `backend/app/api/deps.py` — `CurrentUser` dep (decode JWT → load user); `require_role(*roles)` factory
- `backend/app/main.py` — include auth router; apply auth dependency to all `/api/v1` routers
  **except** `auth/login`; keep `/health` `/readyz` public
- `backend/app/core/config.py` — `auth_enabled` flag (default True; fail-fast if jwt_secret is the `change-me` default outside dev)
- `frontend/src/lib/api/client.ts` — attach `Authorization: Bearer`; on 401 → login
- `frontend/src/App.tsx` — login route + route guard
- replace hardcoded `ui-analyst` id (3 frontend spots, per `docs/QUALITY.md`)
- `infra/scripts/seed.sh` (or new `seed_admin`) — seed initial ADMIN from env, **never hardcoded**
- `infra/scripts/smoke_demo.sh` — login first, pass token on every call
- `backend/tests/conftest.py` — token fixture + auth-bypass/override for existing tests

Tests after: `pytest tests/test_auth.py && pytest`; `npm test && npm run typecheck`;
then `bash infra/scripts/smoke_demo.sh`.

Blockers / risks:
- **Highest cross-cutting risk.** Frontend client, smoke script, and pytest fixtures must
  change in lockstep or the whole app + suite returns 401.
- No users table today → schema + initial-admin seeding (env-driven credentials).
- `conftest.py` has no DB fixture; auth integration tests may need a test DB (see Global risks).

---

## Etap 2 — Rate limiting

**Approach:** `slowapi` (Starlette-native) with in-memory backend (single backend process);
Redis backend optional for scale. Stricter bucket on `auth/login`.

Modify:
- `backend/pyproject.toml` — add `slowapi`
- `backend/app/main.py` — register `Limiter`, exception handler, middleware
- `backend/app/core/config.py` — `rate_limit_default`, `rate_limit_login`, `rate_limit_enabled`
- hot endpoints: `auth/login`, `ingest/upload`, `ingest/replay`, `detection/run`

New:
- `backend/app/core/ratelimit.py` — limiter instance + key function (per-user when authed, else IP)
- `backend/tests/test_ratelimit.py`

Tests after: `pytest tests/test_ratelimit.py`.

Blockers / risks:
- In-memory limiter is **per-process** — won't share across uvicorn workers (single worker today; note for scale).
- Tests must reset limiter state between cases (fixture).

---

## Etap 3 — WebSocket real-time broadcasting

**Approach:** a `ConnectionManager` subscribes to the in-process event bus and fans out to
connected sockets. Services publish **after commit** so no uncommitted state leaks.

New:
- `backend/app/core/ws_manager.py` — ConnectionManager (connect/disconnect/broadcast) + bus subscriber
- `backend/tests/test_stream.py` — connect + receive a broadcast

Modify:
- `backend/app/api/routers/stream.py` — use ConnectionManager; **auth via `?token=` query param** (browsers can't set WS headers)
- `backend/app/core/events.py` — typed event-name constants; isolate handler failures (today `publish` uses `return_exceptions=False`)
- emit `bus.publish(...)` post-commit in: `detection_service.detect_events`,
  `triage_service.triage_alert`, `response_service.recommend_for_alert/approve/reject`,
  `reporting_service.generate_alert_report`
- `backend/app/main.py` — lifespan wires the WS manager to the bus
- `frontend/src/lib/ws.ts` — pass token, reconnect/backoff, typed events
- `frontend/src/pages/DashboardPage.tsx`, `AlertsPage.tsx` — invalidate queries on events

Tests after: `pytest tests/test_stream.py`; `npm test`.

Blockers / risks:
- In-process bus → **single worker only** (document; Redis pub/sub if scaled).
- Publishing must be **post-commit and failure-isolated** so a broken WS handler can't break the detection write path.

---

## Etap 4 — Model drift tracking

**Approach:** unsupervised distribution-shift drift (no production ground truth). Capture a
baseline (class distribution + confidence histogram) at **train time**; compare recent
windows with PSI / KS. Analyst disposition (FALSE_POSITIVE rate) is a secondary proxy.

New:
- `backend/app/models/model_drift.py` — DriftSnapshot(model_version_id FK, window_start/end, n_samples, class_distribution JSONB, mean_confidence, psi, ks, status, created_at)
- `backend/app/services/drift_service.py` — windowing + PSI/KS + persist
- `backend/migrations/versions/0006_model_drift.py`
- `backend/tests/test_drift.py` — pure PSI/KS math + windowing
- `frontend/src/pages/` drift view or Dashboard section + chart

Modify:
- `backend/app/models/__init__.py` — register `DriftSnapshot`
- `backend/app/api/routers/detection.py` — `GET /detection/drift`, `POST /detection/drift/run`
- `ml/train.py`, `ml/metrics.py` — write baseline class distribution + confidence histogram into `metadata.json`
- `frontend/src/lib/api/detection.ts` — drift calls

Tests after: `pytest tests/test_drift.py`.

Blockers / risks:
- No production labels → distribution drift only; accuracy drift needs disposition feedback.
- Baseline captured at train time; **older artifacts lack it** → handle missing baseline gracefully.

---

## Etap 5 — Live packet/flow capture sensor (LAB-ONLY, default OFF)

> ⚠️ **Directly contradicts `docs/ETHICS.md` rule #3 ("No live packet capture").**
> This etap must **rewrite rule #3** into a controlled-capture policy and keep the default OFF.
> Do not start without explicit instructor sign-off.

**Approach:** optional sensor that assembles flows from captured packets into `FlowRecordIn`
and feeds the existing ingestion path. Disabled by default; ADMIN + feature flag required;
RFC1918 / single lab interface only; BPF allowlist; never WAN.

New:
- `backend/app/ingestion/capture/` — `sensor.py` (scapy flow assembly), `runner.py` (background task), `feature_extractor.py` (→ `feature_schema`)
- `backend/app/api/routers/capture.py` — ADMIN-only `POST /capture/start|stop`, `GET /capture/status` (gated by flag + role)
- `backend/tests/test_capture.py` — feature extraction from synthetic packets; flag-off returns disabled/403

Modify:
- `backend/pyproject.toml` — `scapy` as an **optional extra** `[capture]`, not a default dep
- `backend/app/core/config.py` — `capture_enabled=false`, allowed interface, BPF allowlist, RFC1918-only
- `docs/ETHICS.md` — replace rule #3 with the lab-only controlled-capture policy
- `docs/INGESTION.md` — document the sensor
- `Dockerfile` / `docker-compose.yml` — document required `NET_RAW` cap (off by default)
- `frontend/src/pages/IngestionPage.tsx` — ADMIN-only capture panel (optional)

Tests after: `pytest tests/test_capture.py`.

Blockers / risks:
- Needs privileged container (`NET_RAW`), root, a real NIC → **CI cannot run live capture**;
  test the parser/feature-extractor with synthetic pcap, not live traffic.
- Ethics gate: default MUST stay OFF; doc update is mandatory, not optional.

---

## Etap 6 — Lab-only real-response framework (HIGHEST RISK, LAST)

> ⚠️ **Touches the hard guardrail:** DB `CHECK (simulated = TRUE)`
> (`ck_response_actions_simulated_only`) + `ResponseAgent.simulated_only` + ETHICS rule #1.
> Per the directive, only **replace** the guardrail with **stronger** controls — never just remove it.
> Default behavior stays simulated. Requires explicit instructor sign-off.

**Approach:** a pluggable executor with three modes — `SIMULATED` (default, unchanged),
`DRY_RUN` (logs intended real action, performs nothing), `LAB_REAL` (acts only against
allowlisted RFC1918 lab targets). `LAB_REAL` requires: ADMIN role + `real_response_enabled`
flag + per-action explicit approval + target in allowlist. The binary CHECK is replaced by a
**stricter positive constraint**, not dropped.

New:
- `backend/app/services/response_executors/` — driver interface + NoOp/dry-run default + lab drivers
- `backend/migrations/versions/0007_real_response_controls.py` — add `execution_mode` enum +
  `lab_authorization_id`, `target_validated`; **replace** `ck_response_actions_simulated_only`
  with: `simulated = TRUE OR (execution_mode = 'LAB_REAL' AND approved_by IS NOT NULL AND target_validated = TRUE)`
- `backend/tests/test_real_response.py`

Modify:
- `backend/app/models/response_action.py` — add fields; tighten CHECK
- `backend/app/agents/response.py` — `simulated_only` → mode-aware (still defaults simulated)
- `backend/app/services/response_service.py` — `_simulate_execute` → execute via driver; real path enforces all controls
- `backend/app/core/config.py` — `real_response_enabled=false`, lab target allowlist, `dry_run_default=true`
- `docs/ETHICS.md` — replace rule #1 with the multi-control policy
- `frontend/src/components/alerts/*`, `ResponseCenterPage.tsx` — show mode; ADMIN-only confirm for non-simulated

Tests after: `pytest tests/test_real_response.py && pytest tests/test_response.py`.

Blockers / risks:
- Ethics-critical. Default MUST remain simulated; LAB_REAL only against lab-owned RFC1918, never WAN.
- Recommend shipping `DRY_RUN` first; enable `LAB_REAL` only after sign-off.
- The DB constraint stays a **positive guard** — invalid rows must be rejected at the DB layer.

---

## Global blockers & risky assumptions

- **Single-process assumptions:** in-process event bus (etap 3) and in-memory rate limiter
  (etap 2) assume one uvicorn worker. Scaling needs Redis pub/sub + shared limiter store.
- **Auth rollout** (etap 1) is the biggest cross-cutting risk: client + smoke + fixtures must move together.
- **Test DB gap:** `conftest.py` has no DB fixture; most tests are pure. Auth/drift/real-response
  add DB-bound logic — keep pure unit tests for rule/math layers; integration tests need a
  Postgres (or aiosqlite) test DB, which is itself net-new work.
- **Secrets:** `jwt_secret` / `api_key` still ship as `change-me`. Etap 1 should fail-fast on defaults outside dev.
- **Doc drift (resolved):** `docs/ETHICS.md` previously referenced a non-existent `audit_log`
  table; it now correctly documents `agent_decisions` (the actual audit trail).
- **Etaps 5 & 6 require ETHICS rewrites** and instructor sign-off; they contradict current hard rules by design.
