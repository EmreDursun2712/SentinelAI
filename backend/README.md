# SentinelAI — Backend

FastAPI service that hosts the agent workflow (Detection → Triage → Response → Investigation → Reporting), the alert REST API, and the WebSocket event stream.

## Layout

```
app/
├── main.py            FastAPI app factory + lifespan
├── core/
│   ├── config.py      pydantic-settings, env-driven
│   ├── db.py          async SQLAlchemy engine + session + ping
│   ├── events.py      in-process pub/sub
│   ├── errors.py      AppError + exception handlers + error envelope
│   ├── middleware.py  request-ID middleware
│   ├── logging.py     structlog setup
│   └── security.py    API-key + JWT helpers
├── api/
│   ├── deps.py
│   └── routers/       auth, alerts, response, reports, ingest, detection,
│                      dashboard, models, tasks, stream, telemetry, health
├── agents/            the five agent modules + runtime (event dispatcher)
├── ingestion/         CSV parser, feature schema, replayer
├── models/            SQLAlchemy ORM models
├── schemas/           Pydantic DTOs
├── tasks/             arq job cores
└── services/          cross-module orchestration
```

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
uvicorn app.main:app --reload
```

Open http://localhost:8000/docs for the auto-generated OpenAPI UI.

## Environment variables

All settings are read from `SENTINEL_*` environment variables (or a local `.env`).

| Variable                     | Default                                                              | Purpose                          |
| ---------------------------- | -------------------------------------------------------------------- | -------------------------------- |
| `SENTINEL_ENV`               | `development`                                                        | Free-form environment label      |
| `SENTINEL_LOG_LEVEL`         | `info`                                                               | structlog level                  |
| `SENTINEL_DATABASE_URL`      | `postgresql+psycopg://sentinelai:sentinelai@localhost:5432/sentinelai` | SQLAlchemy URL                   |
| `SENTINEL_API_KEY`           | `dev-api-key-change-me`                                              | API-key for service-to-service calls |
| `SENTINEL_JWT_SECRET`        | `dev-jwt-secret-change-me`                                           | JWT signing secret (rotate in prod) |
| `SENTINEL_JWT_ALGORITHM`     | `HS256`                                                              | JWT algorithm                    |
| `SENTINEL_JWT_TTL_MINUTES`   | `720`                                                                | Token lifetime                   |
| `SENTINEL_BOOTSTRAP_ADMIN_USERNAME` | _(unset)_                                                     | If set with the password, creates an ADMIN once on startup |
| `SENTINEL_BOOTSTRAP_ADMIN_PASSWORD` | _(unset)_                                                     | Bootstrap admin password (create-only, never overwrites)   |
| `SENTINEL_CORS_ORIGINS`      | `http://localhost:5173`                                              | Comma-separated allowlist        |
| `SENTINEL_ML_ARTIFACTS_DIR`  | `/app/ml_artifacts`                                                  | Where the model file is loaded   |

### Authentication

Every `/api/v1` route requires a JWT (`Authorization: Bearer <token>`) except
`POST /api/v1/auth/login`; `/health`, `/readyz`, `/docs`, and the OpenAPI schema stay public.
Authorization is method-based RBAC — reads need `VIEWER`+, mutations need `ANALYST`+, user
management needs `ADMIN`. Bootstrap the first admin with the two `BOOTSTRAP_ADMIN` vars above;
no default user is ever created. See [docs/API.md](../docs/API.md#authentication--roles) for
the full flow.

## Health probes

| Endpoint   | Purpose                                                            |
| ---------- | ------------------------------------------------------------------ |
| `/health`  | Liveness — `200 {"status":"ok"}` whenever the process is up        |
| `/readyz`  | Readiness — `200` if DB is reachable, `503` otherwise              |

Why both? Liveness should never check dependencies (a flaky DB shouldn't restart the app).
Readiness is allowed to fail; an orchestrator pulls the pod from rotation without killing it.

## Error envelope

Every error response uses one shape:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed.",
    "details": { "errors": [...] }
  },
  "request_id": "9b8c2f5d4e..."
}
```

Codes used so far: `http_400`, `http_404`, `http_409`, `http_422`, `http_500`,
`validation_error`, `internal_error`, plus domain codes (`not_found`, `conflict`,
`unauthorized`) defined as subclasses of `AppError`.

## Request IDs

Every request is stamped with an `X-Request-ID`:

- If the client sends one, it is preserved end-to-end.
- Otherwise a hex UUID is generated.
- The ID is echoed back in the response header, included in the error envelope, and
  bound to the structlog context so every log line for that request carries it.

## Database & migrations

The app uses **SQLAlchemy 2.x async** with the **psycopg v3** driver. Sessions are
created via `app.api.deps.SessionDep` and yielded per-request.

Alembic is wired against `app.core.db.Base.metadata`. The initial migration
(`0001_initial_schema`) creates every table the system needs.

```bash
# fresh checkout — apply all migrations
docker compose exec backend alembic upgrade head

# autogenerate a new migration after editing models
docker compose exec backend alembic revision --autogenerate -m "add x"

# roll back one step
docker compose exec backend alembic downgrade -1

# print the current head
docker compose exec backend alembic current
```

## Schema

The data model is normalized but tuned for dashboard read patterns. Every table
has `created_at`; mutable tables also have `updated_at`. All datetimes are stored
as `TIMESTAMPTZ`. IP addresses use the Postgres `INET` type.

| Table              | Purpose                                                                         |
| ------------------ | ------------------------------------------------------------------------------- |
| `ingestion_jobs`   | One row per CSV replay (or future live ingestion run); tracks status, progress, errors. |
| `model_versions`   | Registry of trained ML model artifacts. Partial unique index enforces at most one active model. |
| `network_events`   | Normalized flow records (immutable). Indexed by `event_time`, `src_ip`, `dst_ip`. |
| `alerts`           | Central workflow row. Status drives the state machine. Indexed for status/severity dashboards and IP lookups. |
| `alert_artifacts`  | Investigation packets, feature-importance dumps, related-alert sets, raw flows. |
| `agent_decisions`  | Audit trail: one row per (alert, agent) step with structured decision + reasoning JSON. |
| `response_actions` | Proposed actions. `simulated=TRUE` is enforced with a CHECK constraint at the DB layer. |
| `incident_reports` | Per-alert and daily-summary write-ups generated by the Reporting agent.         |

Relationships at a glance:

```
ingestion_jobs ─< network_events ─< alerts >─ model_versions
                                     │
                                     ├─< alert_artifacts
                                     ├─< agent_decisions ─< response_actions
                                     └─< incident_reports
```

State machine on `alerts.status`:

```
NEW → TRIAGED → {AUTO_RESPONDED | AWAITING_ANALYST}
    → INVESTIGATED → REPORTED → CLOSED
```

### Constraints worth noting

- `alerts.confidence` — CHECK `0 ≤ confidence ≤ 1`.
- `response_actions.simulated` — CHECK `simulated = TRUE`. Ethics guardrail.
- `model_versions.(name, version)` — UNIQUE composite.
- `model_versions.is_active` — partial UNIQUE index (`WHERE is_active = TRUE`).
- All status / severity / action-type columns use SQL-portable `VARCHAR + CHECK`
  (via `Enum(..., native_enum=False)`) so future migrations can evolve values
  without touching Postgres enum types.

### Cascade behaviour

| Parent              | Child              | On delete                                            |
| ------------------- | ------------------ | ---------------------------------------------------- |
| `alerts`            | `alert_artifacts`  | CASCADE — artifacts vanish with the alert            |
| `alerts`            | `agent_decisions`  | CASCADE                                              |
| `alerts`            | `response_actions` | CASCADE                                              |
| `alerts`            | `incident_reports` | SET NULL — reports survive an alert deletion         |
| `network_events`    | `alerts.event_id`  | SET NULL                                             |
| `model_versions`    | `alerts`           | SET NULL                                             |
| `ingestion_jobs`    | `network_events`   | SET NULL                                             |
| `agent_decisions`   | `response_actions` | SET NULL                                             |

## Tests

```bash
pytest
```

Test suite uses an in-process ASGI client via `httpx.ASGITransport` — no live server needed.
`tests/test_models.py` validates ORM metadata (table names, indexes, check constraints)
without touching Postgres.
