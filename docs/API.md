# API — Quick tour

The backend exposes its full HTTP surface at `/api/v1` and a WebSocket at `/api/v1/stream`.
OpenAPI documentation is served at `/docs` (Swagger) and `/redoc` when the backend is running.
The machine-readable schema is at `/api/v1/openapi.json`.

## Conventions

- JSON in, JSON out. All bodies are UTF-8 JSON.
- Every response carries an `X-Request-ID` header. If the client sends one, it is preserved.
- **Every `/api/v1` endpoint requires a JWT** (`Authorization: Bearer <token>`), except
  `POST /api/v1/auth/login`. `/health`, `/readyz`, `/docs`, `/redoc`, and
  `/api/v1/openapi.json` stay public. See [Authentication & roles](#authentication--roles).

## Authentication & roles

Obtain a token from `POST /api/v1/auth/login`, then send it as a Bearer header on every
request. Authorization is **method-based RBAC**: reads need `VIEWER`+, mutations need
`ANALYST`+, and a few endpoints require `ADMIN`. Roles are ranked `VIEWER < ANALYST < ADMIN`,
so a higher role satisfies any lower requirement.

| Method | Path                    | Role    | Purpose                                          |
| ------ | ----------------------- | ------- | ------------------------------------------------ |
| POST   | `/api/v1/auth/login`    | public  | Exchange username/password for a JWT             |
| GET    | `/api/v1/auth/me`       | any     | Current identity (decoded from the token)        |
| POST   | `/api/v1/auth/logout`   | any     | Stateless no-op; client discards its token       |
| POST   | `/api/v1/auth/users`    | ADMIN   | Create a user `{username, password, role}`       |

```bash
# 1. Log in
TOKEN=$(curl -fsS localhost:8000/api/v1/auth/login \
  -H 'content-type: application/json' \
  -d '{"username":"admin","password":"<your-admin-pw>"}' | jq -r .access_token)

# 2. Call protected endpoints
curl -fsS localhost:8000/api/v1/alerts -H "Authorization: Bearer $TOKEN"
```

Role policy by endpoint family:

| Family                                                       | Read (GET) | Mutate (POST) |
| ------------------------------------------------------------ | ---------- | ------------- |
| alerts, response, reports, ingestion, detection, dashboard  | VIEWER+    | ANALYST+      |

A `VIEWER` calling a mutation gets **403**; a request with no/invalid token gets **401**.

### Bootstrap admin

The first admin is created on startup from env vars — never hardcoded. Set **both**
`SENTINEL_BOOTSTRAP_ADMIN_USERNAME` and `SENTINEL_BOOTSTRAP_ADMIN_PASSWORD` (or the
`BACKEND_BOOTSTRAP_ADMIN_*` Compose vars). If either is unset, no user is created. The
bootstrap is create-only: it never overwrites an existing user's password. Additional users
are created via `POST /api/v1/auth/users` (ADMIN only).

> **Secret rotation:** `SENTINEL_JWT_SECRET` and `SENTINEL_API_KEY` ship as `change-me`
> placeholders for the classroom demo. Rotate them (and the bootstrap admin password) before
> any shared/exposed deployment — the backend refuses to start in a production-like
> `SENTINEL_ENV` while `JWT_SECRET` is still the default.

## Error envelope

Every non-2xx response has this shape:

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

## Health probes

| Method | Path       | Codes      | Purpose                                                |
| ------ | ---------- | ---------- | ------------------------------------------------------ |
| GET    | `/health`  | 200        | Liveness — always 200 while the process is running    |
| GET    | `/readyz`  | 200, 503   | Readiness — 503 if any dependency (DB) is unreachable |

## Endpoints (Phase 0 scaffolding — full behavior lands in later phases)

| Method | Path                                  | Purpose                                       |
| ------ | ------------------------------------- | --------------------------------------------- |
| GET    | `/api/v1/alerts`                      | List alerts. Filters: `status`, `severity`, `disposition`, `src_ip`, `dst_ip`, `min_priority`. Sort: `created_at`/`priority`/`severity`. |
| GET    | `/api/v1/alerts/stats`                | Counts grouped by status / severity / disposition |
| GET    | `/api/v1/alerts/{id}`                 | Alert detail + full agent-decision audit trail |
| POST   | `/api/v1/alerts/{id}/triage`          | Re-run triage; body `{window_minutes?}`       |
| POST   | `/api/v1/alerts/{id}/disposition`     | Analyst verdict; body `{disposition, note?, analyst_id?}` |
| POST   | `/api/v1/alerts/{id}/investigate`     | Run the Investigation agent; persists `INVESTIGATION_PACKET` artifact |
| POST   | `/api/v1/alerts/{id}/reinvestigate`   | Alias for `/investigate`                      |
| GET    | `/api/v1/alerts/{id}/investigation`   | Return the most recent investigation packet   |
| POST   | `/api/v1/alerts/{id}/report`          | Generate a per-alert incident report          |
| GET    | `/api/v1/alerts/{id}/report`          | Return the most recent per-alert report       |
| POST   | `/api/v1/alerts/{id}/close`           | Analyst close                                 |
| GET    | `/api/v1/response`                    | List actions. Filters: `alert_id`, `status`, `action_type` |
| GET    | `/api/v1/response/pending`            | Pending response actions (Response Center queue) |
| GET    | `/api/v1/response/{id}`               | Single response-action detail                 |
| POST   | `/api/v1/response/recommend/{alert_id}` | Manually generate recommendations            |
| POST   | `/api/v1/response/{id}/approve`       | Simulate-execute the action; body `{analyst_id?, note?}` |
| POST   | `/api/v1/response/{id}/reject`        | Reject; body `{reason, analyst_id?}`          |
| GET    | `/api/v1/reports`                     | List reports. Filters: `kind`, `alert_id`     |
| GET    | `/api/v1/reports/{id}`                | Return the full packet (structured + markdown) |
| GET    | `/api/v1/reports/{id}/markdown`       | Raw markdown (`text/markdown`)                |
| POST   | `/api/v1/reports/daily/run`           | Generate a daily summary; body `{date?}`      |
| POST   | `/api/v1/ingest/upload`               | Multipart CSV upload; returns ingestion summary |
| POST   | `/api/v1/ingest/replay`               | Ingest a CSV from the server-side data dir    |
| POST   | `/api/v1/ingest/flow`                 | Ingest a single flow record (JSON)            |
| GET    | `/api/v1/ingest/jobs`                 | List ingestion jobs                           |
| GET    | `/api/v1/ingest/jobs/{id}`            | Single ingestion job detail                   |
| GET    | `/api/v1/detection/model`             | Currently loaded ML bundle info               |
| POST   | `/api/v1/detection/predict`           | Inference on raw flows (no persistence)       |
| POST   | `/api/v1/detection/events/{id}`       | Detect a stored event; persists alert         |
| POST   | `/api/v1/detection/batch`             | Detect a list of event_ids; persists          |
| POST   | `/api/v1/detection/run`               | Process recent un-detected events             |
| WS     | `/api/v1/stream`                      | Event stream (alert.*, action.*)              |

See [INGESTION.md](INGESTION.md) for the CSV schema, [DETECTION.md](DETECTION.md) for the inference flow, [TRIAGE.md](TRIAGE.md) for severity/priority rules and analyst dispositions, [RESPONSE.md](RESPONSE.md) for recommendation policy and the approval flow, [INVESTIGATION.md](INVESTIGATION.md) for evidence gathering and the summary packet, and [REPORTING.md](REPORTING.md) for incident-report generation and daily summaries.

## Event stream payloads

```json
{ "type": "alert.created",     "payload": { "id": 42, "severity": null } }
{ "type": "alert.triaged",     "payload": { "id": 42, "severity": "HIGH" } }
{ "type": "alert.responded",   "payload": { "id": 42, "action": "BLOCK_IP", "simulated": true } }
{ "type": "alert.investigated","payload": { "id": 42 } }
{ "type": "alert.reported",    "payload": { "id": 42, "report_id": 7 } }
```
