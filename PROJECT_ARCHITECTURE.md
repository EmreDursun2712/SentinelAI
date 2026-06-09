# SentinelAI — Project Architecture

**AI-Driven Intrusion Detection and Response Dashboard**

Term project for a third-year Computer and Network Security course. SentinelAI
ingests network-flow records, detects suspicious traffic with a CIC-IDS2017-trained
classifier, and walks each alert through a five-stage agent workflow (Detect →
Triage → Respond → Investigate → Report). Response actions are **simulated by
default**: no real firewall, host, or third-party system is touched unless an
operator explicitly enables the gated, lab-only response mode.

This document describes the system **as built**. The authoritative, always-current
API reference is [docs/API.md](docs/API.md); per-subsystem deep-dives live under
[docs/](docs/).

---

## 0. Implementation status

The system is fully implemented, tested (353 backend unit + 62 real-Postgres
integration + 92 frontend + 33 ML tests; Playwright e2e specs), and runs with
`make bootstrap`. Production-grade capabilities — the unsafe ones **off by
default**:

| Capability | State | Default | Reference |
| --- | --- | --- | --- |
| **Cookie + JWT auth + RBAC** | Implemented | All `/api/v1` protected | [docs/AUTH.md](docs/AUTH.md) |
| **Rate limiting** (Redis) | Implemented | On (in-proc fallback in dev) | [docs/RATE_LIMITING.md](docs/RATE_LIMITING.md) |
| **WebSocket broadcasting** (Redis pub/sub) | Implemented | On (token-authenticated) | [docs/API.md](docs/API.md) |
| **Async task queue** (arq worker) | Implemented | On (no-op without Redis) | [docs/TASK_QUEUE.md](docs/TASK_QUEUE.md) |
| **Model drift + analyst-feedback quality** | Implemented | On (read), analyst-run | [docs/MODEL_DRIFT.md](docs/MODEL_DRIFT.md) |
| **Model lifecycle** (activate/rollback/shadow) | Implemented | On (ADMIN to mutate) | [docs/MODEL_LIFECYCLE.md](docs/MODEL_LIFECYCLE.md) |
| **Data retention + soft-delete** | Implemented | **OFF** (0 = disabled) | [docs/DATA_RETENTION.md](docs/DATA_RETENTION.md) |
| **Live-flow sensor** (Zeek/Suricata logs) | Implemented | **OFF** — lab-only | [docs/LIVE_SENSOR.md](docs/LIVE_SENSOR.md) |
| **Lab-only real response** | Implemented | **OFF** — simulated | [docs/LAB_RESPONSE.md](docs/LAB_RESPONSE.md) |

**Safety invariants enforced in code:** a response action is `simulated` unless
it is an explicit `LAB` action (Postgres CHECK
`ck_response_actions_simulated_unless_lab`); a real LAB effect requires response
enabled + `mode=lab` + a lab executor + an allowlisted target CIDR + analyst
approval, and is reversible; the sensor refuses to start without
`SENTINEL_SENSOR_ENABLED=true` + authorized CIDRs and reads flow **metadata only**
(no NIC binding, no packet capture, no payloads). See [docs/ETHICS.md](docs/ETHICS.md).

---

## 1. Architecture overview

### 1.1 Style

**Modular monolith.** One FastAPI backend, one React frontend, one PostgreSQL
database, one Redis instance, one arq worker, and an offline ML package — plus an
optional standalone log-tailing sensor. Backend modules are organized by domain
(agents, ingestion, api, services, core, models) with clear interfaces. This keeps
the demo a single `docker compose up` while staying correct behind multiple
workers (Redis fans out WebSocket events and backs the rate limiter + queue).

### 1.2 High-level diagram

```
        ┌──────────────────────────────────────────────────────────────┐
        │                     React + TypeScript UI                     │
        │  Dashboard · Alerts · Alert detail · Response · Reports ·     │
        │  Ingestion · System · Admin/Users    (TanStack Query + WS)    │
        └───────────────┬──────────────────────────┬───────────────────┘
            REST (cookie/Bearer + CSRF)        WebSocket (?token=JWT)
                        │                          │
        ┌───────────────▼──────────────────────────▼───────────────────┐
        │                FastAPI backend (modular monolith)             │
        │  api/routers: auth alerts response reports ingest detection   │
        │               dashboard models tasks stream telemetry health  │
        │  agents: detection triage response investigation reporting    │
        │  services: detection drift model_lifecycle retention task …   │
        │  core: db · config · security · events(agents) · broadcast    │
        │        · ratelimit · queue · ws_manager · metrics · tracing   │
        └───────┬─────────────────────┬──────────────────────┬─────────┘
                │                     │                       │
        ┌───────▼────────┐   ┌────────▼────────┐    ┌─────────▼─────────┐
        │ PostgreSQL 16  │   │   Redis 7       │    │  arq worker       │
        │ alerts, events,│   │ rate limiter +  │    │ (same services,   │
        │ agent_decisions│   │ WS pub/sub +    │    │  long-running     │
        │ (audit), …     │   │ task queue      │    │  jobs)            │
        └────────────────┘   └─────────────────┘    └───────────────────┘

        ┌──────────────────────────────────────────────────────────────┐
        │ ml/ (offline): train.py → ml/artifacts/<version>/             │
        │   model.joblib · metadata.json (classes, feature_order,       │
        │   baseline, calibration, hpo) — loaded by the detection path  │
        └──────────────────────────────────────────────────────────────┘

        ┌──────────────────────────────────────────────────────────────┐
        │ sensor/ (optional, lab-only): tails Zeek/Suricata flow logs   │
        │   → POST /api/v1/ingest/flows (metadata only, allowlisted)    │
        └──────────────────────────────────────────────────────────────┘
```

### 1.3 Stack decisions

| Concern | Choice | Why |
| --- | --- | --- |
| Backend framework | FastAPI + Uvicorn (async) | Typed, OpenAPI for free, first-class WebSockets. |
| ORM / migrations | SQLAlchemy 2 (async) + Alembic | Real migrations (`0001`–`0012`), tested up/down. |
| Database | PostgreSQL 16 | JSONB payloads, INET/CIDR types, partial/unique indexes. |
| Cache / fan-out | Redis 7 | Rate-limit counters, cross-worker WS pub/sub, arq queue. |
| Task queue | arq (Redis) | Offload heavy jobs; status tracked in the `tasks` table. |
| ML | scikit-learn + pandas + joblib | CIC-IDS2017 RandomForest/GradientBoosting; optional HPO + calibration. |
| Frontend | React 18 + TypeScript + Vite | Strict typing mirrors the OpenAPI schema (codegen). |
| UI | Tailwind CSS + hand-built primitives + Recharts | No UI-kit dependency; `src/components/ui/`. |
| Data fetching | TanStack Query | Caching, polling, optimistic updates, WS invalidation. |
| Container | Docker Compose | One command brings the whole stack online. |
| Auth | JWT access (in memory) + refresh session (httpOnly cookie) + CSRF | Practical, production-shaped auth; see §2.6. |

---

## 2. Agent modules — responsibilities

Each agent is a plain Python class under `backend/app/agents/`. They register
handlers on the in-process **event dispatcher** (`core/events.py`) at startup
(`agents/runtime.register_agents`, called from the app lifespan) and share state
via the database. The workflow is a deterministic state machine driven by alert
status transitions.

**Event-driven workflow (agents subscribe to events):**

```
ingestion.job_completed → DetectionAgent  (REPLAY jobs, if auto-run configured)
alert.created           → TriageAgent      (triage if still NEW)
alert.triaged           → ResponseAgent    (recommend if TRIAGED, no actions yet)
alert.responded         → InvestigationAgent (only if SENTINEL_INVESTIGATION_AUTO)
alert.investigated      → ReportingAgent   (only if SENTINEL_REPORTING_AUTO)
```

Handlers are **idempotent and state-guarded**: the synchronous detection pipeline
(`detect_events`) triages + responds inline in one transaction, so the event
handlers see the alert already advanced and no-op — repeated/duplicate events
never double-process. Investigation + Reporting stay analyst-triggered unless their
automation flag is set.

**Workflow state machine:**

```
NEW → TRIAGED → {AUTO_RESPONDED | AWAITING_ANALYST} → INVESTIGATED → REPORTED → CLOSED
```

**Events emit after commit** (post-commit pattern): services publish only once a
transaction has committed, so rolled-back work is never dispatched or broadcast.

**WebSocket fan-out is cross-worker** via Redis pub/sub (`core/broadcast.py`):
domain events are published to a Redis channel that every backend process
subscribes to and re-broadcasts to its own local WebSocket clients — so the
dashboard works behind multiple workers/replicas. Without Redis (dev) it falls
back to a single-process local broadcast. The in-process event bus drives the
**agents** (once, on the originating worker); the broadcaster drives **WebSocket
delivery** (every worker).

### 2.1 Detection Agent — `agents/detection.py`

Loads the trained pipeline (`ml/artifacts/latest/`) into a process-wide registry,
aligns each `network_events.features` JSONB to the model's `feature_order`, runs
`predict_proba`, and creates an `Alert` (status `NEW`) when a non-benign class
clears the confidence threshold. It checks **feature coverage** (warns, or
optionally fails, when too many trained features are missing) and writes an
`agent_decisions` row (`agent=DETECTION`) with the full probability vector.

### 2.2 Triage Agent — `agents/triage.py`

Assigns severity (`LOW/MEDIUM/HIGH/CRITICAL`) and a numeric priority from model
confidence, attack-family weight, and recent-activity signals; sets status
`TRIAGED`; writes a `TRIAGE` decision row.

### 2.3 Response Agent — `agents/response.py` (simulated by default; lab-only real)

The `response_rules` engine proposes an ordered action list by severity
(`BLOCK_IP`, `RATE_LIMIT`, `ISOLATE_HOST`, `NOTIFY_ANALYST`, `CREATE_TICKET`,
`ESCALATE`, `ISOLATE_ALERT`, `SUPPRESS_ALERT`, `NO_ACTION`). LOW/MEDIUM
approval-actions set `AWAITING_ANALYST`; HIGH/CRITICAL auto-execute the
**simulated** safe actions (`AUTO_RESPONDED`).

Each action carries an `execution_mode`: `SIMULATED` (default, no real effect) or
`LAB`. A network action becomes `LAB` only when lab response is explicitly enabled
**and** the target is in an allowlisted lab CIDR; LAB network actions **always
require analyst approval** (never auto-executed, even at CRITICAL) and run through a
`ResponseExecutor` (`simulated` / `mock_lab` / `nftables_lab`) with **rollback**
(`POST /response/{id}/rollback`). The DB CHECK
`ck_response_actions_simulated_unless_lab` makes a non-simulated row impossible
outside LAB mode. See [docs/LAB_RESPONSE.md](docs/LAB_RESPONSE.md).

### 2.4 Investigation Agent — `agents/investigation.py`

Builds an investigation packet — top feature contributions (from the model's
`feature_importances_`), related alerts/events by `src_ip`/`dst_ip`, a timeline,
and templated next steps — and persists it as an **`alert_artifacts` row**
(`kind=INVESTIGATION_PACKET`, JSONB). Sets status `INVESTIGATED`.

### 2.5 Reporting Agent — `agents/reporting.py`

Generates a **per-alert report** and a **daily summary** as structured JSON
rendered to **Markdown** (`reporting_renderer.py`). Rows go in `incident_reports`;
the markdown file is written under `backend/data/reports/`. *(PDF is not generated;
`pdf_path` is reserved/nullable. Export to PDF externally, e.g. `pandoc`.)* Sets
status `REPORTED`.

### 2.6 Auth, rate limiting & realtime (cross-cutting)

- **Auth.** Short-lived JWT **access token** (Bearer, held in memory by the SPA)
  + long-lived **refresh session** in an httpOnly Secure cookie with server-side
  revocation; cookie-authenticated mutations require **double-submit CSRF**.
  Method-based **RBAC** (`VIEWER < ANALYST < ADMIN`); every protected request
  re-checks `is_active` + token version. Account lockout + password policy.
  ([docs/AUTH.md](docs/AUTH.md))
- **Rate limiting.** Redis sliding-window, per-policy buckets, keyed per user
  (per IP+username for login); `429` + `Retry-After`. Required in prod.
- **Realtime.** Token-authenticated WebSocket `/api/v1/stream` (rejects bad tokens
  with close code 1008) broadcasting domain events after commit.
- **Async work.** `POST /api/v1/tasks/*` enqueues onto the arq worker and returns a
  task id; status in the `tasks` table + live `task.updated` events.

---

## 3. Folder structure

```
SentinelAI/
├── README.md
├── PROJECT_ARCHITECTURE.md          ← this document
├── SECURITY.md
├── docker-compose.yml · Makefile · .env.example
│
├── backend/
│   ├── pyproject.toml · alembic.ini · Dockerfile · openapi.json
│   ├── app/
│   │   ├── main.py                  ← app factory + lifespan (router mounts)
│   │   ├── worker.py                ← arq WorkerSettings
│   │   ├── core/                    db, config, security, cookies, csrf,
│   │   │                              events, broadcast, ratelimit, queue,
│   │   │                              ws_manager, metrics, tracing, logging
│   │   ├── models/                  alert, network_event, agent_decision,
│   │   │                              alert_artifact, response_action,
│   │   │                              incident_report, ingestion_job, task,
│   │   │                              user, auth_session, model_version,
│   │   │                              model_drift, model_activation,
│   │   │                              model_shadow_eval, enums, mixins
│   │   ├── schemas/                 pydantic DTOs per resource
│   │   ├── agents/                  base, detection, triage, response,
│   │   │                              investigation, reporting, runtime
│   │   ├── ingestion/               parser, feature_schema, replayer
│   │   ├── api/routers/             auth alerts response reports ingest
│   │   │                              detection dashboard models tasks
│   │   │                              stream telemetry health
│   │   ├── services/                detection, drift, model_lifecycle,
│   │   │                              model_registry, retention, task,
│   │   │                              reporting, triage, response, …
│   │   ├── tasks/jobs.py            arq job cores
│   │   └── scripts/                 dump_openapi, retention CLI
│   ├── migrations/versions/         0001 … 0012
│   ├── tests/  +  tests/integration/
│   └── data/{samples,reports}/
│
├── frontend/
│   ├── package.json · vite.config.ts · tailwind.config.ts · playwright.config.ts
│   ├── src/
│   │   ├── main.tsx · App.tsx       providers + route table
│   │   ├── lib/api/                 typed client + per-resource modules +
│   │   │                              generated schema.d.ts (OpenAPI codegen)
│   │   ├── lib/{auth,toast,confirm,stream}/   contexts/providers
│   │   ├── components/{ui,charts,alerts,dashboard,models,layout,...}
│   │   ├── components/ErrorBoundary.tsx
│   │   └── pages/                   Dashboard, Alerts, AlertDetail, Response,
│   │                                 Reports, Ingestion, System, AdminUsers, Login
│   └── e2e/                         Playwright specs
│
├── ml/
│   ├── train.py · evaluate.py · synthetic.py · profiles.py · hpo.py
│   ├── calibration.py · baseline.py · pipeline.py · preprocess.py
│   ├── tests/  +  artifacts/<version>/{model.joblib,metadata.json,…}
│
├── sensor/                          optional Zeek/Suricata log-tailer (lab-only)
├── infra/                           scripts (bootstrap, seed, smoke, e2e,
│                                     backup/restore), postgres/init.sql,
│                                     single-container/ (reverse-proxy/TLS in
│                                     docs/DEPLOYMENT_SECURITY.md)
└── docs/                            architecture, ethics, auth, deployment,
                                     API, quality, per-subsystem guides
```

---

## 4. Database entities

All tables use `BIGINT` identity PKs and (most) `created_at` / `updated_at`.
JSONB holds flexible payloads; INET/CIDR for network identity. Schema is built and
verified through Alembic migrations `0001`–`0012` (up *and* down tested in the
integration suite).

| Table | Purpose / notable columns |
| --- | --- |
| `network_events` | Ingested flows: `event_time`, `src/dst_ip` (INET), ports, `protocol`, `features` (JSONB), `label`, `detected_at`. |
| `alerts` | One per suspicious flow: snapshot of network identity, `prediction`, `confidence`, `severity`, `priority`, `status`, `disposition`, `model_version_id`, `event_id` (FK SET NULL), `archived_at` (soft-delete). |
| `agent_decisions` | **Audit trail** — one row per agent step *and* analyst action (`agent` ∈ DETECTION/TRIAGE/RESPONSE/INVESTIGATION/REPORTING/ANALYST), `decision` + `reasoning` JSONB. |
| `alert_artifacts` | Investigation packets + other artifacts (`kind`, JSONB `data`). |
| `response_actions` | `action_type`, `simulated`, `execution_mode`, `status`, `approved_by`, `payload`, `rollback_status`, `executor_name`, `expires_at`. CHECK: `simulated` unless LAB. |
| `incident_reports` | `kind` (PER_ALERT/DAILY_SUMMARY), `title`, `packet` (JSONB), `md_path`, `pdf_path` (nullable), `archived_at`. |
| `ingestion_jobs` | Replay/stream jobs: `kind`, `source`, `status`, counts. |
| `model_versions` | Registry: `name`, `version`, `algorithm`, `classes`, `feature_order`, `metrics`, `artifact_path`, `is_active` (partial unique: one active). |
| `model_drift_snapshots` | PSI feature/prediction drift + `confidence_stats` + analyst-`feedback` quality proxy + `status`. |
| `model_activations` | Append-only activate/rollback audit (`action`, `model_version_id`, `previous_version_id`, `actor`, `reason`). |
| `model_shadow_evals` | Candidate-vs-active comparison (`agreement_rate`, `metrics`). |
| `tasks` | Background jobs: `kind`, `status`, `progress`, `params`, `result`, `created_by`. |
| `users` | `username`, `password_hash`, `role`, `is_active`, `token_version`, lockout fields. |
| `auth_sessions` | Refresh-token sessions (hashed), for rotation + revocation. |

> There is **no `audit_log` table and no `assets` table** — auditing is
> `agent_decisions`; triage weighting is computed in code, not from an asset table.

---

## 5. API surface

All routes are mounted under `/api/v1`; the WebSocket is at `/api/v1/stream`.
Health/readiness/metrics live at the root. The **authoritative reference with
request/response shapes, auth, pagination, and error envelope** is
[docs/API.md](docs/API.md). Router groups:

`auth` · `alerts` · `response` · `reports` · `ingest` · `detection` ·
`dashboard` · `models` (lifecycle) · `tasks` · `stream` · `telemetry` · `health`.

Highlights: cookie+Bearer auth with CSRF; list endpoints expose totals via the
`X-Total-Count` header (or `{items,…}` envelopes); `/detection/drift/*`;
`/models` activate/rollback/shadow; `/tasks/*` async jobs; `/ingest/flows` +
`/ingest/sensor/status`; `/response/{id}/rollback`; data-retention is operated via
CLI/task, off by default.

---

## 6. End-to-end data flow

```
1. A CIC-IDS2017-style CSV row is ingested (upload/replay) or arrives from the
   optional sensor → ingestion/parser normalizes it → network_events row.
        ▼
2. Detection (sync pipeline or the detection task) aligns features to the model's
   feature_order, runs predict_proba; non-benign ≥ threshold → Alert(NEW) + a
   DETECTION agent_decisions row.  (Triage + Response run inline in the same txn.)
        ▼
3. Triage sets severity/priority (TRIAGED). Response proposes actions:
   HIGH/CRITICAL auto-simulate (AUTO_RESPONDED); LOW/MEDIUM await analyst
   (AWAITING_ANALYST). Real LAB actions always await approval.
        ▼
4. (human) Analyst approves/rejects in the Response Center; LAB actions are
   reversible. Optimistic UI + a success/error toast; every decision audited.
        ▼
5. Investigation builds a packet (alert_artifacts), INVESTIGATED.
        ▼
6. Reporting renders a markdown report (incident_reports), REPORTED; analyst CLOSEs.
        ▼
7. Every committed step publishes a domain event → Redis pub/sub → all workers →
   WebSocket → the React UI invalidates queries and updates live.
```

CPU-bound work (`predict_proba` on a batch) is offloaded to a worker thread; truly
long jobs (large batches, reports, daily summary, drift, retention, retrain) run on
the arq worker.

---

## 7. Quality & operations

- **Tests.** `make test` (backend pytest + frontend vitest), `make
  test-integration` (real Postgres via testcontainers — migrations up/down, FK/
  CHECK/unique constraints, committing transactions), `make typecheck`, `make
  lint`, `npm run test:e2e` (Playwright), and `infra/scripts/smoke_demo.sh`.
- **CI.** GitHub Actions: `backend` (ruff + pytest + integration), `frontend`
  (typecheck + vitest + build, advisory Playwright e2e), `security` (pip-audit /
  npm audit / SBOM). Dependabot weekly. See [docs/QUALITY.md](docs/QUALITY.md).
- **Observability.** Prometheus `/metrics`, opt-in OpenTelemetry tracing,
  structured logs with a per-request id + bound user/role, structured `/readyz`.
- **Backups/DR.** `make backup-db` / `make restore-db`
  ([docs/BACKUP_DR.md](docs/BACKUP_DR.md)).
- **Deployment.** Compose dev + production-like reverse proxy + TLS in
  [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md); security posture in
  [docs/DEPLOYMENT_SECURITY.md](docs/DEPLOYMENT_SECURITY.md).

---

## 8. Ethics & safety guardrails

- **Simulated by default.** `ResponseAction.simulated` is true unless an explicit
  `LAB` action; the DB CHECK `ck_response_actions_simulated_unless_lab` makes a
  real (non-simulated) row impossible outside LAB mode.
- **Lab-only real response.** LAB is off by default and, when enabled, acts only on
  **allowlisted lab CIDRs**, requires **analyst approval**, and is **reversible** —
  never public or external targets. ([docs/LAB_RESPONSE.md](docs/LAB_RESPONSE.md))
- **No packet capture, metadata only.** No NIC binding / `tcpdump` / `pcap`. The
  optional sensor reads flow *logs* (Zeek/Suricata), off by default, scoped to
  authorized lab CIDRs; payloads are never read or stored.
  ([docs/LIVE_SENSOR.md](docs/LIVE_SENSOR.md))
- **AuthN/Z everywhere.** Every `/api/v1` endpoint requires auth (except login,
  refresh, telemetry, health/readyz/docs); RBAC restricts mutations to
  ANALYST+/ADMIN.
- **No external exfiltration.** Reports are written only to the local
  `data/reports/` volume; the codebase ships no firewall/EDR/ticketing/chat client.
- **Auditable.** Every agent step and analyst action is appended to
  `agent_decisions`; model activations/rollbacks to `model_activations`.

See [docs/ETHICS.md](docs/ETHICS.md). Adding any real-action driver beyond the
gated lab framework requires explicit course-instructor approval.
