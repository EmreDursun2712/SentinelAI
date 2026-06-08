# Async Task Queue

Long-running work — large detection batches, report generation, the daily
summary, drift checks, retention cleanup, and (optional) model retraining — runs
on a **Redis-backed [arq](https://arq-docs.helpmanual.io/) worker** instead of
blocking an HTTP request thread. The API returns a **task id** immediately;
status is observable from the API and the dashboard.

arq (not RQ) was chosen because the backend is fully async: the worker calls the
exact same `async` services (`detect_events`, `generate_alert_report`,
`run_drift_check`, …) the synchronous endpoints use — no sync/async bridging.

## How it works

```
client ──POST /api/v1/tasks/…──▶ API: insert Task(PENDING) ──enqueue──▶ Redis queue
                                   │                                        │
                                   └──────── returns Task(id) ◀── 201       ▼
                                                                    arq worker
                                                          mark_running → progress → SUCCEEDED/FAILED
                                                                    │ (updates the Task row)
                                  WebSocket  ◀── task.updated event ─┘ (Redis pub/sub → all API workers)
```

- The **`tasks` table** is the source of truth (`PENDING → RUNNING →
  SUCCEEDED | FAILED | CANCELLED`, plus `progress`, `params`/`result` JSONB,
  `error`, `created_by`, timestamps). The API reads status from the DB, so it's
  available and RBAC-filterable even if Redis/worker hiccups.
- The worker emits a `task.updated` event per transition; via the Redis
  broadcaster it reaches WebSocket clients on any API worker, so the UI updates
  live (it also polls as a fallback).
- **No Redis configured?** Enqueue is a no-op (the `Task` row stays `PENDING`)
  so dev without a worker still serves the synchronous endpoints. Production
  requires Redis (fails closed at startup).

## Task kinds

| Kind | Endpoint | Service it runs |
| --- | --- | --- |
| `DETECTION_RUN` | `POST /api/v1/tasks/detection-run` | classify undetected events (idempotent) |
| `DRIFT_RUN` | `POST /api/v1/tasks/drift-run` | drift snapshot over a window |
| `DAILY_SUMMARY` | `POST /api/v1/tasks/daily-summary` | daily incident summary report |
| `REPORT_ALERT` | `POST /api/v1/tasks/report/{alert_id}` | per-alert incident report |
| `RETENTION_CLEANUP` | `POST /api/v1/tasks/retention-cleanup` (ADMIN) | delete old terminal tasks + drift snapshots |
| `ML_RETRAIN` | `POST /api/v1/tasks/retrain` (ADMIN, gated) | retrain the model (`SENTINEL_ML_RETRAIN_ENABLED=true`) |

## API

| Method | Path | Role | Purpose |
| --- | --- | --- | --- |
| GET | `/api/v1/tasks` | VIEWER+ | List tasks (own; ADMIN sees all). Filters: `status`, `kind`, `limit`, `offset`. |
| GET | `/api/v1/tasks/{id}` | VIEWER+ | One task (owner or ADMIN; 404 otherwise). |
| POST | `/api/v1/tasks/*` | ANALYST+ | Enqueue a job → returns the `Task`. Admin-only for retention/retrain. |

Safety: creation is method-RBAC'd (ANALYST+) and rate-limited per user
(`SENTINEL_RATE_LIMIT_TASKS`, default `30/minute`) to prevent job spam.
Visibility is owner-scoped (admins see all). Jobs are idempotent where it matters
(detection only processes undetected events; lifecycle transitions are sticky on
terminal state), so a duplicate/retried run doesn't double-process.

```bash
TASK=$(curl -fsS -X POST localhost:8000/api/v1/tasks/detection-run \
  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"limit":5000}' | jq -r .id)
curl -fsS localhost:8000/api/v1/tasks/$TASK -H "Authorization: Bearer $TOKEN" | jq '{status,progress,result}'
```

## Running the worker

**Docker Compose** ships a `worker` service (same image as the backend, run with
`arq app.worker.WorkerSettings`):

```bash
docker compose up -d            # postgres, redis, backend, worker, frontend
docker compose logs -f worker
```

**Locally** (backend venv, Redis reachable):

```bash
cd backend && arq app.worker.WorkerSettings
```

Readiness: `GET /readyz` includes a `queue` check (Redis reachability for the
queue; informational — the API serves without a worker). The `worker` container
has its own healthcheck (`arq --check app.worker.WorkerSettings`).

## Configuration

| Env | Default | Notes |
| --- | --- | --- |
| `SENTINEL_REDIS_URL` | _(none)_ | Required for the queue (and rate limiting/WS) in prod. |
| `SENTINEL_TASK_QUEUE_NAME` | `sentinelai:queue` | arq queue name (API + worker must match). |
| `SENTINEL_RATE_LIMIT_TASKS` | `30/minute` | Per-user task-creation limit. |
| `SENTINEL_RETENTION_DAYS` | `90` | Default age cutoff for retention cleanup. |
| `SENTINEL_ML_RETRAIN_ENABLED` | `false` | Gate the heavy retrain task/endpoint. |

## Tests

- `backend/tests/test_tasks.py` — queue no-op, RBAC (401/403), retrain gate.
- `backend/tests/integration/test_tasks.py` — real-DB create/get/list (RBAC),
  lifecycle transitions + terminal idempotency, and worker job cores
  (daily-summary success, detection-without-model failure, retention cleanup).
- `frontend/src/lib/stream/invalidate.test.ts` — `task.*` → `["tasks"]`.
