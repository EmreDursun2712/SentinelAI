# Implementation Backlog — remaining hardening gaps

Audit-only planning artifact. **No application code is changed by this document.**
It maps every known remaining gap to the exact files/modules that must change,
proposes a safe implementation order, and flags risky migrations, test impact,
and backwards-compatibility needs. The six original gaps (auth, rate limiting,
WS broadcast, real response, live capture, drift) are already closed — see
[HARDENING_PLAN.md](HARDENING_PLAN.md). This backlog covers the *next* layer.

> Status legend: 🟢 low risk · 🟡 medium · 🔴 high (schema/security/behavioral).

---

## 0. Current commands (confirmed)

```bash
# Backend tests (host venv)         | container equivalent
cd backend && pytest                # docker compose run --rm --no-deps --entrypoint pytest backend -q
# Frontend
cd frontend && npm test             # vitest run
cd frontend && npm run typecheck    # tsc --noEmit
# Quality gates
make test         # backend pytest + frontend vitest
make typecheck    # tsc --noEmit
make lint         # ruff check . && ruff format --check .
# Stack / demo
make bootstrap    # build + wait health + seed model + restart   (infra/scripts/bootstrap.sh)
make demo         # bootstrap + demo-seed                         (infra/scripts/demo_seed.sh)
make smoke        # 11-step e2e (needs SENTINELAI_PASSWORD or BACKEND_BOOTSTRAP_ADMIN_PASSWORD)
make up | down | reset | seed | logs | shell-db
```

Migration head: `0007_lab_response_controls`. New migrations chain from there.
sklearn is pinned `==1.9.0` in both `backend/pyproject.toml` and `ml/pyproject.toml`.

---

## 1. Gap → file map

### A. CI/CD missing 🟢
- **New** `.github/workflows/ci.yml`: jobs for backend (`pip install -e ".[dev]"` → ruff check + format --check + pytest), frontend (`npm ci` → `tsc --noEmit` + `vitest run`), sensor (`cd sensor && pip install -e ".[dev]" && pytest`).
- **New** `.github/workflows/e2e.yml` (optional): `docker compose up -d` → migrate → seed → `smoke_demo.sh` → teardown.
- Touches: none of `app/` — pure CI. Test impact: surfaces the pre-existing repo-wide `ruff` `UP042`/format drift (fix or `--exit-zero` first; see §H).

### B. Real PostgreSQL integration tests missing 🟡
- **`backend/pyproject.toml`** dev extras: add `pytest-postgresql` *or* `testcontainers[postgres]`.
- **`backend/tests/conftest.py`**: add a session-scoped Postgres engine fixture + a function-scoped `AsyncSession` that runs `alembic upgrade head` (or `Base.metadata.create_all`) against a throwaway DB, plus a fixture overriding `app.api.deps.db_session`.
- **New** `backend/tests/integration/` (mark `@pytest.mark.integration`): real CRUD for detection→triage→response, FK/CHECK enforcement (esp. `ck_response_actions_simulated_unless_lab`), `drift_service.run_drift_check`, `ingestion_service.insert_flow_batch`.
- **`backend/pyproject.toml`** `[tool.pytest.ini_options]`: register the `integration` marker; keep default run unit-only (`-m "not integration"`) so DB-less runs stay green.
- Backwards-compat: existing stubbed tests stay; integration is additive/opt-in.

### C. Frontend page/E2E tests shallow 🟡
- **`frontend/package.json`** dev deps: `@playwright/test` (E2E) — RTL is already present.
- **New** `frontend/src/pages/__tests__/` (vitest+RTL): `LoginPage`, `ResponseCenterPage` (LAB approve confirm path), `DashboardPage` (ModelHealthPanel states) with `authApi`/query mocks.
- **New** `frontend/e2e/` (Playwright): login→dashboard, simulated approve, LAB approve typed-confirm, drift run. Needs a running stack (gate behind `make e2e` / CI service).
- **`Makefile`**: add `e2e` target.

### D. Alembic downgrade paths untested 🟡
- Covered by §B harness: **new** `backend/tests/integration/test_migrations.py` — `upgrade head` → `downgrade base` → `upgrade head` round-trip; assert each `0001`–`0007` `downgrade()` runs. 🔴 *Risk*: `0004`/`0007` rewrite CHECK constraints and `0007` drops columns — downgrade must run on an **empty** DB or after purging LAB rows; document that downgrade is destructive for LAB data.

### E. JWT refresh / revocation missing 🔴
- **`backend/app/core/security.py`**: add `create_refresh_token` + `token jti` claim; helpers to hash/verify refresh tokens.
- **New model + migration** `0008_refresh_tokens` (or a Redis denylist of revoked `jti`): table `refresh_tokens(id, user_id, jti, expires_at, revoked_at)`; index on `jti`/`user_id`.
- **`backend/app/api/routers/auth.py`**: `POST /auth/refresh`, make `/auth/logout` revoke; issue refresh on `/auth/login`.
- **`backend/app/api/deps.py`** `get_current_user`: optional denylist check (per-request DB/Redis hit — a deliberate change from the current stateless design; document the latency trade-off).
- **`backend/app/core/config.py`**: `jwt_refresh_ttl_minutes`.
- **Frontend** `lib/auth/AuthContext.tsx` + `lib/api/client.ts`: refresh-on-401 retry flow.
- Backwards-compat: existing short-lived access tokens keep working; refresh is additive. 🔴 *Test impact*: `tests/test_auth.py` must add refresh/revoke cases; the "stateless, no per-request DB" claim in `docs/AUTH.md` changes.

### F. Tokens in localStorage → httpOnly cookies 🔴
- **`backend/app/api/routers/auth.py`**: set the access (and refresh) token as `HttpOnly; Secure; SameSite=Strict` cookies on login; clear on logout.
- **`backend/app/api/deps.py`**: read the bearer token from the cookie (fallback to `Authorization` header for the sensor/service callers and tests).
- **CSRF**: new double-submit token or `SameSite` reliance — **new** `app/core/csrf.py` + middleware; affects all mutating endpoints.
- **Frontend** `lib/api/client.ts` (`credentials: "include"`, drop `Authorization`), `lib/auth/token.ts` (remove/repurpose), `AuthContext.tsx`.
- 🔴 *Interacts with* the **sensor** (`sensor/sentinelai_sensor/client.py`) which uses a bearer header — keep header-auth for non-browser callers. *Test impact*: many `tests/*` build `Authorization` headers; keep header path working so they don't all churn.

### G. Password policy + account lockout weak 🟡
- **`backend/app/schemas/auth.py`** `CreateUserRequest`: stronger validation (length/complexity) via a validator.
- **`backend/app/services/user_service.py`** `authenticate`: track failed attempts → lock after N within a window. Store counters in **Redis** (preferred, reuses the rate-limit client) or a `users.failed_attempts/locked_until` column (**migration**).
- **`backend/app/core/config.py`**: `auth_max_failed_attempts`, `auth_lockout_minutes`, `auth_password_min_length`.
- Note: login is already IP+username rate-limited (`docs/RATE_LIMITING.md`); lockout is the per-account complement.

### H. Security headers / CSP / HSTS / CORS / TLS 🟢🟡
- **New** `backend/app/core/middleware.py` `SecurityHeadersMiddleware` (CSP, HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy) added in **`backend/app/main.py:create_app`** (order: after RequestId, before/around CORS).
- **`backend/app/main.py`** CORS: tighten `allow_methods`/`allow_headers` from `*`; keep `cors_origins_list`.
- **`infra/`** + **`docs/`**: TLS termination via the reverse proxy (`infra/single-container/spa_server.py` / a new nginx conf) + a `docs/DEPLOYMENT.md` (TLS, headers, prod env).
- 🟡 *CSP risk*: the Vite dev server + inline styles may need a dev-vs-prod CSP; verify the dashboard still loads.

### I. Dependency / security scanning 🟢
- **`.github/workflows/ci.yml`**: add `pip-audit` (backend+sensor) and `npm audit --audit-level=high` (frontend) steps.
- **New** `.github/dependabot.yml`: pip (backend, sensor, ml), npm (frontend), github-actions.
- **Optional** CodeQL workflow + an SBOM (`cyclonedx`) artifact.

### J. Observability: metrics / tracing / dashboards 🟡
- **`backend/pyproject.toml`**: `prometheus-client` (+ optional `opentelemetry-*`).
- **New** `backend/app/core/metrics.py`: counters/histograms (request latency, alerts created, response actions by mode, drift score gauge, rate-limit hits).
- **`backend/app/main.py`**: expose `GET /metrics` (public or API-key), wire a metrics middleware; emit from `detection_service`, `response_service`, `drift_service`, `ratelimit`.
- **`infra/`**: optional Prometheus + Grafana compose profile + a dashboard JSON.
- Backwards-compat: additive. *Test impact*: a smoke test that `/metrics` renders.

### K. Readiness only checks DB (not Redis/model) 🟢
- **`backend/app/api/routers/health.py`** `readyz`: also probe Redis (via `app.core.ratelimit.get_rate_limiter()` — add an async `ping()`/health method to limiters) and report model-loaded (`get_model_registry().is_loaded()`); return per-dependency status.
- **`backend/app/core/ratelimit.py`**: add `ping`/`health` to `RateLimiter` impls.
- *Test impact*: update `tests/test_health.py` readiness assertions (currently `db` only).

### L. Backup / DR strategy 🟢
- **New** `infra/scripts/backup.sh` (`pg_dump`) + `restore.sh`; **`Makefile`** `backup`/`restore` targets; **`docs/DEPLOYMENT.md`** retention + restore runbook. Compose: document the `postgres_data` volume + the `down -v` warning (already in QUALITY.md).

### M. Single-process WS / event bus / rate-limit 🔴
- **`backend/app/core/events.py`**: add a Redis pub/sub transport behind the existing `EventBus` interface (publish → Redis channel; a subscriber task feeds local handlers) so multiple workers share events.
- **`backend/app/core/ws_manager.py`** + **`backend/app/main.py`** lifespan: start the Redis subscriber; each worker broadcasts to its own sockets.
- Rate limiting already uses Redis when configured (`docs/RATE_LIMITING.md`) — only the in-process fallback is single-worker; document "Redis required for multi-worker".
- 🔴 *Risk*: ordering/at-least-once semantics; needs an integration test with 2 workers. Backwards-compat: in-process bus stays the default for single-worker/dev.

### N. No real task queue 🟡
- **New** worker service (`arq` preferred — already on Redis; or Celery). New `backend/app/worker.py` + tasks for `generate_alert_report`/`generate_daily_summary` (PDF/markdown), `run_drift_check`, large `detect_events` batches.
- **`backend/app/services/*`**: split "enqueue" vs "run"; **routers** return `202 Accepted` + a job id for long ops.
- **`docker-compose.yml`**: a `worker` service (reuses backend image, different command).
- 🟡 *Risk*: response contract change for long endpoints (now async) → frontend must poll/subscribe. Backwards-compat: keep sync path for small inputs.

### O. Agent runtime not fully event-driven 🟡
- **`backend/app/agents/*.py`** `register()` (currently no-ops in `detection.py`/`response.py`): subscribe handlers to `EventBus` event types.
- **`backend/app/main.py`** lifespan: instantiate + `register()` agents on startup.
- **`backend/app/services/*`**: move the manual `publish_event` calls to flow through agent subscriptions (e.g. ingestion completion → detection agent → triage → response).
- 🟡 *Risk*: double-execution if both the direct service calls and the subscriptions fire — needs careful migration + tests. Backwards-compat: keep direct calls until subscriptions proven; feature-flag the runtime.

### P. ML maturity 🟡🔴
- **`ml/pipeline.py`**: wrap classifier in `CalibratedClassifierCV` (confidence calibration — triage/threshold depend on it); add HPO (`GridSearchCV`/`Optuna`).
- **`ml/train.py`**: real CIC-IDS2017 path hardening, persist calibration + HPO params into `metadata.json`.
- **Feature parity** (the QUALITY.md skew): align `ml/feature_list.py` ↔ `backend/app/ingestion/feature_schema.py` + the synthetic/demo CSV column set.
- **Feedback drift**: **`backend/app/services/drift_service.py`** — incorporate analyst disposition (FALSE_POSITIVE rate) as a supervised-proxy signal alongside PSI.
- **Model rollout/rollback**: **`backend/app/services/model_registry.py`** + a `POST /api/v1/detection/model/activate/{version}` endpoint + a `model_versions` staged/active workflow (the partial-unique `is_active` index already exists); optional shadow scoring. 🔴 *Risk*: changing the active model mid-stream affects detection determinism.

### Q. API gaps (totals / retention / codegen) 🟢🟡
- **Total counts**: **`backend/app/schemas/common.py`** add a `Page[T]{items,total,limit,offset}` wrapper; update list endpoints (`alerts.py` `list_alerts`/`list` patterns, `response.py`, `reports.py`, `ingest.py jobs`) to return totals (or an `X-Total-Count` header). 🟡 *Frontend breaking*: `lib/api/*` + pages consume bare arrays today → coordinate the shape change (or use the header to avoid breakage).
- **Retention/cleanup**: **new** `backend/app/services/retention_service.py` + a scheduled job (ties to §N worker) to prune old `network_events`/`alerts`/`model_drift_snapshots`; config TTLs.
- **OpenAPI→TS codegen**: **`frontend/package.json`** `openapi-typescript` dev dep + a `gen:api` script reading `/api/v1/openapi.json` → replaces hand-kept `frontend/src/lib/types.ts`. 🟡 Large diff in `types.ts` + all consumers; do incrementally.

### R. Frontend UX 🟢
- **Toasts**: add `sonner` (or a small custom) provider in **`frontend/src/main.tsx`**; replace inline-only errors in `ResponseCenterPage`, `AlertActionBar`, `ResponseActionsTable`.
- **Modal**: **new** `frontend/src/components/ui/Modal.tsx` + a `useConfirm` hook to replace `window.prompt`/`confirm` in the LAB approve + rollback flows.
- **ErrorBoundary**: **new** `frontend/src/components/ErrorBoundary.tsx` wrapping `<App/>` in `main.tsx`.
- **a11y**: ARIA/focus/keyboard pass on `Button`, `Select`, `Table`, modal, login form.
- **Optimistic updates**: TanStack `onMutate` in approve/reject/disposition mutations.

### S. DevEx / docs 🟢
- **New** `.pre-commit-config.yaml`: `ruff` (lint+format) for `backend`+`sensor`, `prettier`/`tsc` for `frontend`. Resolves the repo-wide ruff drift in one pass (`UP042`, formatting).
- **`Makefile`**: add `e2e` (boot compose → smoke → teardown) and `backup`/`restore`.
- **Docs/code fixes**: `PROJECT_ARCHITECTURE.md` still describes an `audit_log` table (actual: `agent_decisions`) — update the §4 entity. Keep `docs/QUALITY.md` test inventory counts current.

---

## 2. Safe implementation order

Ordered by value/effort and dependency. Each phase ends green (`make test`, `make typecheck`, smoke).

1. **Phase 1 — Guardrails & hygiene (low risk, high signal)**: A (CI), I (scanning + dependabot), S (pre-commit + Makefile e2e + doc fixes), K (readiness), L (backup), H (security headers + CORS tighten + DEPLOYMENT.md). *Mostly additive; CI will first force the ruff drift cleanup.*
2. **Phase 2 — Test depth**: B (PG integration harness) → D (migration round-trip, built on B) → C (frontend page tests + Playwright). *Establishes the safety net before behavioral changes.*
3. **Phase 3 — Observability**: J (metrics) + optional tracing + Grafana profile. *Additive; benefits later phases.*
4. **Phase 4 — Auth hardening (behavioral, needs Phase 2 net)**: G (password policy + lockout) → E (refresh/revocation) → F (httpOnly cookies + CSRF). *Do G first (cheap), then E, then F; F is the riskiest (CSRF + sensor header path).*
5. **Phase 5 — API & UX**: Q (totals → retention → codegen) + R (toast/modal/ErrorBoundary/a11y/optimistic). *Q's shape changes are frontend-breaking — pair with R.*
6. **Phase 6 — Scale & ML (largest)**: N (task queue) → M (Redis event bus, multi-worker) → O (event-driven agents) → P (calibration/HPO/feature-parity/feedback-drift/rollout). *Highest risk; do last, behind flags, with the Phase 2 integration tests.*

---

## 3. Risk register (migrations, tests, backwards-compat)

| Item | Migration | Backwards-compat / risk |
| --- | --- | --- |
| E refresh/revocation | `0008` refresh_tokens (or Redis denylist) | Changes per-request auth to optionally hit a store; `docs/AUTH.md` "stateless" claim updates; access tokens keep working. |
| F httpOnly cookies | none | **Must keep header auth** for sensor + tests; adds CSRF to all mutations. |
| G lockout | maybe `users.failed_attempts/locked_until` (or Redis) | Prefer Redis to avoid a migration. |
| D downgrade tests | none | `0004`/`0007` CHECK swaps + `0007` column drops → downgrade destructive for LAB rows; run on empty DB. |
| Q totals | none | List response shape changes → frontend breaking; prefer `X-Total-Count` header to stay compatible. |
| M Redis bus | none | At-least-once / ordering; in-process default preserved. |
| N task queue | none | Long endpoints become `202`+poll → frontend + smoke updates. |
| P rollout | `model_versions` workflow (index exists) | Changing active model affects detection determinism; gate + shadow first. |

**Test-suite-wide impact:** B/D add a real DB harness (new dev deps, marker, default `-m "not integration"`). E/F/G touch `tests/test_auth.py`. K touches `tests/test_health.py`. Q touches response-shape assertions across `tests/test_*` + frontend. CI (A) will fail until the pre-existing ruff `UP042`/format drift (S) is resolved — sequence S before/with A.

---

## 4. Audit report (summary)

- **Completeness:** every listed gap (A–S above) is mapped to concrete files/modules; none omitted.
- **No behavioral change made** — this is the plan only (plus this doc).
- **Safe-by-default preserved:** none of these stages reopen the six closed gaps; auth/rate-limit/WS/drift stay on, sensor + real response stay off by default.
- **Biggest hidden risk:** lack of a real-DB test harness (§B) — adding it first de-risks every later schema/behavioral change (notably E, F, M, N, P).
- **Lowest-effort/highest-value next step:** Phase 1 (CI + pre-commit + scanning + security headers + readiness + backup) — small, additive, and immediately improves the project's professional posture.
- **Recommended entry point:** §S (pre-commit, clears ruff drift) → §A (CI) so the rest of the work lands behind a green gate.
