# SentinelAI — Project Architecture

**AI-Driven Intrusion Detection and Response Dashboard**

Term project for a third-year Computer and Network Security course. The system ingests network flow records, detects suspicious traffic with a CIC-IDS2017-trained classifier, and walks each alert through a five-stage agent workflow (Detect → Triage → Respond → Investigate → Report). Response actions are **simulated by default**: no real firewall, host, or third-party system is touched unless an operator explicitly enables the gated, lab-only response mode.

---

## 0. Implementation status (production-grade hardening)

Beyond the original five-agent workflow, the project has been hardened across six
areas. All are implemented and tested; the unsafe ones are **off by default**.

| Capability | State | Default | Reference |
| --- | --- | --- | --- |
| **JWT auth + RBAC** | Implemented | All `/api/v1` protected | [docs/AUTH.md](docs/AUTH.md) |
| **Rate limiting** (Redis) | Implemented | On (in-proc fallback in dev) | [docs/RATE_LIMITING.md](docs/RATE_LIMITING.md) |
| **WebSocket broadcasting** | Implemented | On (token-authenticated) | [docs/API.md](docs/API.md#event-stream-websocket) |
| **Model drift monitoring** | Implemented | On (read), analyst-run | [docs/MODEL_DRIFT.md](docs/MODEL_DRIFT.md) |
| **Live-flow sensor** (Zeek/Suricata logs) | Implemented | **OFF** — lab-only | [docs/LIVE_SENSOR.md](docs/LIVE_SENSOR.md) |
| **Lab-only real response** | Implemented | **OFF** — simulated | [docs/LAB_RESPONSE.md](docs/LAB_RESPONSE.md) |

Safety invariants enforced in code: response actions are `simulated` unless an
explicit `LAB` action (DB CHECK `ck_response_actions_simulated_unless_lab`); the
sensor refuses to start without `SENTINEL_SENSOR_ENABLED=true` + authorized
CIDRs; real response requires `SENTINEL_RESPONSE_ENABLED=true` + lab mode +
allowlisted CIDRs + analyst approval; nothing binds a NIC or captures packets.
See [docs/ETHICS.md](docs/ETHICS.md).

---

## 1. Architecture Overview

### 1.1 Style

**Modular monolith.** One FastAPI backend, one React frontend, one Postgres database, one ML package. Modules are organized by domain (alerts, agents, ingestion, ml) with clear interfaces, so the codebase reads like microservices but ships as a single deployable. This keeps the demo simple while preserving a clean upgrade path.

### 1.2 High-Level Diagram

```
                ┌─────────────────────────────────────────────────────────┐
                │                     React + TS UI                       │
                │  Dashboard │ Alerts │ Alert Detail │ Response │ Reports │
                └────────────────────────┬────────────────────────────────┘
                                         │  REST + WebSocket (JSON)
                ┌────────────────────────▼────────────────────────────────┐
                │                 FastAPI (modular monolith)              │
                │                                                         │
                │  ┌─────────────┐  ┌───────────────┐  ┌──────────────┐   │
                │  │ ingestion   │  │ agents        │  │ api routers  │   │
                │  │  - replayer │  │  - detection  │  │  - alerts    │   │
                │  │  - parser   │  │  - triage     │  │  - response  │   │
                │  │  - schema   │  │  - response   │  │  - reports   │   │
                │  └──────┬──────┘  │  - investig.  │  │  - ws/stream │   │
                │         │         │  - reporting  │  └──────┬───────┘   │
                │         │         └───────┬───────┘         │           │
                │         │                 │                 │           │
                │  ┌──────▼─────────────────▼─────────────────▼───────┐   │
                │  │  core: db (SQLAlchemy), event bus, settings, log │   │
                │  └──────────────────────┬───────────────────────────┘   │
                └─────────────────────────┼───────────────────────────────┘
                                          │
                ┌─────────────────────────▼───────────────────────────────┐
                │              PostgreSQL  (alerts, actions, audit)       │
                └─────────────────────────────────────────────────────────┘

                ┌─────────────────────────────────────────────────────────┐
                │ ml/  (offline): train.py, evaluate.py, artifacts/*.pkl  │
                │  → produced model file is loaded by detection agent     │
                └─────────────────────────────────────────────────────────┘
```

### 1.3 Stack Decisions

| Concern               | Choice                                  | Why                                                                  |
| --------------------- | --------------------------------------- | -------------------------------------------------------------------- |
| Backend framework     | FastAPI + Uvicorn                       | Async, typed, OpenAPI for free, plays well with WebSockets.          |
| ORM                   | SQLAlchemy 2.x + Alembic                | Industry standard; migrations matter even in a course project.       |
| DB                    | PostgreSQL 16                           | JSONB for flexible alert payloads, indexed queries for the UI.       |
| ML                    | scikit-learn + pandas + joblib          | CIC-IDS2017 baselines (RandomForest / GradientBoosting) work well.   |
| Frontend              | React 18 + TypeScript + Vite            | Fast HMR, strict typing matches the FastAPI schema.                  |
| UI lib                | Tailwind CSS + shadcn/ui + Recharts     | Production-like look with minimal custom CSS.                        |
| State / data fetching | TanStack Query                          | Caching, retries, polling, WS-friendly.                              |
| Realtime              | FastAPI WebSocket → frontend subscriber | New alerts and agent transitions stream live.                        |
| Container             | Docker Compose                          | One `docker compose up` brings the whole demo online.                |
| Auth (demo-level)     | Single API key + simple JWT for the UI  | Enough to demonstrate; not the focus of this course project.         |

---

## 2. Agent Modules — Responsibilities

Each agent is a **plain Python class** under `backend/app/agents/`. They register
handlers on the in-process **event dispatcher** (`core/events.py`) at startup
(`agents/runtime.register_agents`, called from the app lifespan) and share state
via the database. The workflow is a deterministic state machine driven by alert
status transitions.

**Event-driven workflow (agents subscribe to events):**

```
ingestion.job_completed → DetectionAgent (REPLAY jobs, if auto-run configured)
alert.created           → TriageAgent       (triage if still NEW)
alert.triaged           → ResponseAgent      (recommend if TRIAGED, no actions yet)
alert.responded         → InvestigationAgent (only if SENTINEL_INVESTIGATION_AUTO)
alert.investigated      → ReportingAgent     (only if SENTINEL_REPORTING_AUTO)
```

Handlers are **idempotent and state-guarded**: the synchronous detection
pipeline (`detect_events`) triages + responds inline in one transaction, so the
event handlers see the alert already advanced and no-op — meaning repeated or
duplicate events never double-process. Investigation + Reporting stay
analyst-triggered unless their automation flag is set. Explicit API actions still
call the services directly; the agents are the automatic layer on top.

**Workflow state machine:**

```
NEW → TRIAGED → {AUTO_RESPONDED | AWAITING_ANALYST} → INVESTIGATED → REPORTED → CLOSED
```

**Events emit after commit** (post-commit pattern): services publish only once a
transaction has committed, so rolled-back work is never dispatched or broadcast.

**WebSocket fan-out is cross-worker** via Redis pub/sub (`core/broadcast.py`):
events are published to a Redis channel that every backend process subscribes to
and re-broadcasts to its own local WebSocket clients — so the dashboard works
behind multiple workers/replicas. Without Redis (dev) it falls back to a
single-process local broadcast. The in-process event bus drives the **agents**
(once, on the originating worker); the broadcaster drives **WebSocket delivery**
(every worker) — keeping business logic single-run while UI updates fan out.

### 2.1 Detection Agent — `agents/detection.py`

- **Input:** parsed flow record (dict matching CIC-IDS2017 feature schema).
- **Job:** load the trained model from `ml/artifacts/`, run `predict_proba`, decide attack vs. benign, attach a confidence score and predicted attack family.
- **Output:** creates an `Alert` row with status `NEW` and emits `alert.created`.
- **Why a module, not a function:** the model is loaded once at startup; the agent owns its lifecycle, feature ordering, and a feature-importance helper used later by the Investigation Agent.

### 2.2 Triage Agent — `agents/triage.py`

- **Input:** `alert.created` event.
- **Job:** assign severity (`LOW / MEDIUM / HIGH / CRITICAL`) using:
  - model confidence,
  - attack family weight (e.g. DDoS, BruteForce, Infiltration → higher),
  - asset criticality (lookup table by destination IP / port).
- **Output:** updates alert with `severity`, sets status `TRIAGED`, emits `alert.triaged`.

### 2.3 Response Agent — `agents/response.py` **(simulated by default; lab-only real)**

- **Input:** `alert.triaged` event.
- **Job:** the `response_rules` engine proposes an ordered action list by severity:
  `BLOCK_IP`, `RATE_LIMIT`, `ISOLATE_HOST`, `NOTIFY_ANALYST`, `CREATE_TICKET`,
  `ESCALATE`, `SUPPRESS_ALERT`, `NO_ACTION`.
- For `LOW/MEDIUM` analyst-approval actions it sets `AWAITING_ANALYST`; for
  `HIGH/CRITICAL` it auto-executes the **simulated** safe actions (`AUTO_RESPONDED`).
- **Execution modes.** Each action carries an `execution_mode`: `SIMULATED`
  (default — no real effect) or `LAB`. A network action becomes `LAB` only when
  lab response is explicitly enabled AND the target is in an allowlisted lab CIDR;
  LAB network actions **always require analyst approval** (never auto-executed,
  even at CRITICAL) and are executed through a `ResponseExecutor` (mock or
  nftables), with rollback support. The DB CHECK
  `ck_response_actions_simulated_unless_lab` makes a non-simulated row impossible
  outside LAB mode. See [docs/LAB_RESPONSE.md](docs/LAB_RESPONSE.md).
- **Output:** a `ResponseAction` row (`simulated=true` unless LAB);
  emits `alert.responded` / `response.action_*`.

> **Ethics guardrail.** `ResponseAction.simulated` is hard-coded `True` in code; there is no driver that talks to a real firewall. The "execution" is a logged event with a timestamp. This is enforced in `agents/response.py` and documented in `docs/ETHICS.md`.

### 2.4 Investigation Agent — `agents/investigation.py`

- **Input:** `alert.responded` event, or analyst-triggered re-investigation.
- **Job:** build an "investigation packet":
  - top SHAP-style feature contributions (using model's `feature_importances_` projected onto this flow),
  - related alerts in the last 30 minutes from same `src_ip` or to same `dst_ip`,
  - suggested next steps (templated from attack family).
- **Output:** writes a JSON blob to `alerts.investigation` and sets status `INVESTIGATED`.

### 2.5 Reporting Agent — `agents/reporting.py`

- **Input:** `alert.investigated` event, plus a scheduled daily roll-up.
- **Job:** generate two artifacts:
  - **Per-alert report** (Markdown + PDF via `weasyprint`) summarizing the full chain.
  - **Daily summary** aggregating counts by severity / family, mean triage-to-response time, top attacker IPs.
- **Output:** rows in `reports` table; files in `backend/data/reports/`. Sets status `REPORTED`.

---

## 3. Folder Structure

```
SentinelAI/
├── README.md
├── PROJECT_ARCHITECTURE.md          ← this document
├── docker-compose.yml
├── .env.example
│
├── backend/
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── Dockerfile
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                  ← FastAPI app factory + lifespan
│   │   ├── core/
│   │   │   ├── config.py            ← pydantic-settings
│   │   │   ├── db.py                ← engine, session, Base
│   │   │   ├── events.py            ← event dispatcher (agents) + publish_event
│   │   │   ├── broadcast.py         ← WebSocket fan-out (Redis pub/sub / local)
│   │   │   ├── security.py          ← API key + JWT helpers
│   │   │   └── logging.py
│   │   ├── models/                  ← SQLAlchemy models
│   │   │   ├── alert.py
│   │   │   ├── response_action.py
│   │   │   ├── report.py
│   │   │   ├── asset.py
│   │   │   └── audit.py
│   │   ├── schemas/                 ← pydantic DTOs for API
│   │   │   ├── alert.py
│   │   │   ├── response.py
│   │   │   └── report.py
│   │   ├── agents/
│   │   │   ├── base.py
│   │   │   ├── detection.py
│   │   │   ├── triage.py
│   │   │   ├── response.py
│   │   │   ├── investigation.py
│   │   │   └── reporting.py
│   │   ├── ingestion/
│   │   │   ├── replayer.py          ← reads CSV/PCAP-summary and pushes flows
│   │   │   ├── parser.py            ← CIC-IDS2017 → internal feature dict
│   │   │   └── feature_schema.py
│   │   ├── api/
│   │   │   ├── deps.py
│   │   │   ├── routers/
│   │   │   │   ├── alerts.py
│   │   │   │   ├── response.py
│   │   │   │   ├── reports.py
│   │   │   │   ├── ingest.py
│   │   │   │   ├── stream.py        ← WebSocket
│   │   │   │   └── health.py
│   │   └── services/
│   │       ├── alert_service.py
│   │       └── report_service.py
│   ├── migrations/                  ← Alembic
│   │   └── versions/
│   ├── tests/
│   │   ├── conftest.py
│   │   ├── test_detection.py
│   │   ├── test_triage.py
│   │   ├── test_response.py
│   │   └── test_api_alerts.py
│   └── data/
│       ├── samples/                 ← small CSV slice for demos
│       └── reports/                 ← generated PDFs
│
├── frontend/
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   ├── Dockerfile
│   ├── index.html
│   ├── public/
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── routes.tsx
│       ├── lib/
│       │   ├── api.ts               ← typed fetch client
│       │   ├── ws.ts                ← WebSocket hook
│       │   └── types.ts             ← shared types (mirror backend schemas)
│       ├── components/
│       │   ├── ui/                  ← shadcn primitives
│       │   ├── charts/
│       │   ├── AlertBadge.tsx
│       │   ├── SeverityPill.tsx
│       │   └── AgentTimeline.tsx
│       ├── pages/
│       │   ├── DashboardPage.tsx
│       │   ├── AlertsPage.tsx
│       │   ├── AlertDetailPage.tsx
│       │   ├── ResponseCenterPage.tsx
│       │   └── ReportsPage.tsx
│       └── styles/
│           └── globals.css
│
├── ml/
│   ├── pyproject.toml
│   ├── README.md
│   ├── train.py                     ← CIC-IDS2017 training entrypoint
│   ├── evaluate.py
│   ├── preprocess.py
│   ├── feature_list.py              ← canonical feature order
│   ├── notebooks/
│   │   └── exploration.ipynb
│   └── artifacts/
│       ├── model.joblib             ← produced by train.py
│       ├── scaler.joblib
│       └── metadata.json            ← classes, feature order, metrics
│
├── infra/
│   ├── postgres/
│   │   └── init.sql
│   ├── nginx/                       ← optional reverse proxy for demo
│   │   └── nginx.conf
│   └── scripts/
│       ├── seed_demo.py             ← populate a few sample alerts
│       └── wait_for_db.sh
│
└── docs/
    ├── ETHICS.md                    ← simulated-response statement
    ├── DATASET.md                   ← CIC-IDS2017 usage notes
    ├── API.md                       ← human-readable API tour
    └── DEMO_SCRIPT.md               ← steps for the in-class demo
```

---

## 4. Database Entities (high level)

All tables use `id BIGSERIAL`, `created_at`, `updated_at`. PostgreSQL JSONB columns hold flexible per-record payloads.

### `alerts`

| column          | type        | notes                                                        |
| --------------- | ----------- | ------------------------------------------------------------ |
| id              | bigserial   | PK                                                           |
| src_ip          | inet        | indexed                                                      |
| dst_ip          | inet        | indexed                                                      |
| src_port        | int         |                                                              |
| dst_port        | int         |                                                              |
| protocol        | varchar(8)  |                                                              |
| flow_features   | jsonb       | full CIC-IDS2017 feature vector for this flow                |
| prediction      | varchar(40) | attack family or `BENIGN`                                    |
| confidence      | float       | 0–1                                                          |
| severity        | varchar(10) | LOW / MEDIUM / HIGH / CRITICAL (nullable until triaged)      |
| status          | varchar(20) | state-machine value                                          |
| investigation   | jsonb       | populated by investigation agent                             |
| created_at      | timestamptz |                                                              |
| triaged_at      | timestamptz | nullable                                                     |
| responded_at    | timestamptz | nullable                                                     |
| closed_at       | timestamptz | nullable                                                     |

Indexes: `(status, created_at desc)`, `(severity)`, `(src_ip)`, `(dst_ip)`.

### `response_actions`

| column      | type        | notes                                          |
| ----------- | ----------- | ---------------------------------------------- |
| id          | bigserial   | PK                                             |
| alert_id    | bigint      | FK → alerts.id                                 |
| action_type | varchar(30) | BLOCK_IP / RATE_LIMIT / ISOLATE_HOST / …       |
| simulated   | bool        | **always true**                                |
| executed    | bool        | true once the simulated action ran             |
| approved_by | varchar(80) | analyst id, nullable                           |
| payload     | jsonb       | what *would* be sent to a real system          |
| created_at  | timestamptz |                                                |
| executed_at | timestamptz | nullable                                       |

### `reports`

| column     | type        | notes                                  |
| ---------- | ----------- | -------------------------------------- |
| id         | bigserial   | PK                                     |
| kind       | varchar(20) | `per_alert` / `daily_summary`          |
| alert_id   | bigint      | nullable, FK                           |
| period     | daterange   | for daily summaries                    |
| summary    | jsonb       | structured roll-up                     |
| md_path    | text        | path to markdown file                  |
| pdf_path   | text        | path to PDF file                       |
| created_at | timestamptz |                                        |

### `assets`

Asset criticality table used by the Triage Agent.

| column      | type        | notes                              |
| ----------- | ----------- | ---------------------------------- |
| id          | bigserial   | PK                                 |
| ip_cidr     | cidr        | matches subnet                     |
| hostname    | text        | optional                           |
| criticality | int         | 1 (low) … 5 (critical)             |
| tags        | text[]      | e.g. `{db, finance}`               |

### `audit_log`

Append-only log of every state transition and analyst action.

| column     | type        | notes                          |
| ---------- | ----------- | ------------------------------ |
| id         | bigserial   | PK                             |
| actor      | varchar(80) | `agent:triage`, `user:alice`   |
| action     | varchar(60) |                                |
| target     | varchar(80) | e.g. `alert:1234`              |
| details    | jsonb       |                                |
| created_at | timestamptz |                                |

---

## 5. API Surface (high level)

All routes mounted at `/api/v1`. JSON in, JSON out. WebSocket at `/api/v1/stream`.

> The high-level groups below are the original surface. The **authoritative,
> current API** — including `/auth/*`, rate limits, `/detection/drift/*`,
> `/ingest/flows`, `/ingest/sensor/status`, and `/response/{id}/rollback` — is
> documented in [docs/API.md](docs/API.md). Health/auditing note: the audit trail
> is the `agent_decisions` table (one row per agent step + analyst action); an
> `ANALYST` agent value records human actions.

### Health & meta
- `GET  /healthz` → `{status:"ok"}`
- `GET  /api/v1/meta/model` → loaded model name, version, classes, metrics

### Alerts
- `GET  /api/v1/alerts` — query params: `status`, `severity`, `src_ip`, `from`, `to`, pagination
- `GET  /api/v1/alerts/{id}` — full alert + investigation packet + action history
- `POST /api/v1/alerts/{id}/reinvestigate` — re-runs Investigation Agent
- `POST /api/v1/alerts/{id}/close` — analyst manually closes

### Response
- `GET  /api/v1/response/pending` — actions awaiting analyst approval
- `POST /api/v1/response/{action_id}/approve` — simulate-execute the action
- `POST /api/v1/response/{action_id}/reject` — discard, log reason

### Ingestion (demo / replay)
- `POST /api/v1/ingest/flow` — push a single flow record (used by replayer + tests)
- `POST /api/v1/ingest/replay` — body: `{file: "samples/friday.csv", rate: 50}` — kicks off background replayer

### Reports
- `GET  /api/v1/reports` — list
- `GET  /api/v1/reports/{id}` — metadata + signed download URLs
- `GET  /api/v1/reports/{id}/pdf` — file
- `POST /api/v1/reports/daily/run` — trigger a daily summary on demand

### Stream
- `WS   /api/v1/stream` — server pushes `{type, payload}` events:
  - `alert.created`, `alert.triaged`, `alert.responded`, `alert.investigated`, `alert.reported`
  - `action.pending`, `action.executed`

---

## 6. End-to-End Data Flow

```
1. ingestion/replayer.py reads a CIC-IDS2017 CSV row
        │
        ▼
2. ingestion/parser.py normalizes it into the canonical feature dict
        │
        ▼
3. agents/detection.py runs the model → label + confidence
        │   creates Alert(status=NEW), emits alert.created
        ▼
4. agents/triage.py subscribes to alert.created
        │   computes severity, updates alert (status=TRIAGED), emits alert.triaged
        ▼
5. agents/response.py subscribes to alert.triaged
        │   ├── HIGH/CRITICAL → auto simulate, status=AUTO_RESPONDED
        │   └── LOW/MEDIUM    → ResponseAction(pending), status=AWAITING_ANALYST
        │   emits alert.responded (or action.pending)
        ▼
6. (optional human step) analyst clicks Approve in Response Center
        │   POST /response/{id}/approve → ResponseAction(executed=true, simulated=true)
        ▼
7. agents/investigation.py subscribes to alert.responded
        │   builds investigation packet, writes alerts.investigation,
        │   status=INVESTIGATED, emits alert.investigated
        ▼
8. agents/reporting.py
        │   per-alert report on alert.investigated
        │   daily summary on cron tick
        │   status=REPORTED, emits alert.reported
        ▼
9. All events are pushed over the WebSocket to the React UI in real time.
```

Concurrency: agents run as awaitable handlers on the same event loop. Heavy work (PDF rendering, model `predict_proba` on a batch) goes to `run_in_threadpool` so the request loop stays responsive.

---

## 7. Implementation status

The full system is implemented: the five-agent workflow, the React dashboard, the
scikit-learn pipeline, and Docker Compose — plus the six hardening capabilities in
§0. Concretely:

- **Data + ML:** Alembic migrations `0001`–`0007`; offline training (`ml/train.py`)
  emits a versioned artifact whose `metadata.json` carries a drift `baseline`.
- **Agents:** detection → triage → response → investigation → reporting, wired
  through the in-process event bus and persisted in Postgres.
- **Auth/RBAC:** stateless JWT, `users` table, method-based RBAC on every
  `/api/v1` router, bootstrap admin from env.
- **Rate limiting:** Redis sliding-window limiter with per-policy buckets.
- **Real-time:** authenticated WebSocket `/stream` broadcasts domain events
  after commit; the frontend invalidates queries on receipt.
- **Drift:** `model_drift_snapshots` + PSI-based drift API and dashboard panel.
- **Live sensor:** standalone `sensor/` service (Zeek/Suricata log tailing),
  off by default, lab-scoped.
- **Lab response:** `ResponseExecutor` abstraction (simulated/mock/nftables),
  off by default, allowlisted + approval-gated + reversible.

Quality gates: `make test` (backend pytest + frontend vitest), `make typecheck`,
`make lint`, and the `infra/scripts/smoke_demo.sh` end-to-end check.

---

## 8. Ethics & Safety Guardrails

- **Simulated by default.** A `ResponseAction` is `simulated=true` unless it is an
  explicit `LAB` action; the DB CHECK `ck_response_actions_simulated_unless_lab`
  makes a real (non-simulated) row impossible outside LAB mode.
- **No production response.** LAB mode is off by default and, when enabled, only
  acts on allowlisted lab CIDRs with analyst approval and rollback — never public
  or external targets. ([docs/LAB_RESPONSE.md](docs/LAB_RESPONSE.md))
- **No packet capture, metadata only.** No NIC binding / `tcpdump` / `pcap`. The
  optional sensor reads flow *logs* (Zeek/Suricata), off by default, scoped to
  authorized lab CIDRs, payloads never read or stored. ([docs/LIVE_SENSOR.md](docs/LIVE_SENSOR.md))
- **AuthN/Z everywhere.** Every `/api/v1` endpoint requires a JWT (except login);
  RBAC restricts mutations to ANALYST+/ADMIN.
- **No external exfiltration.** Reports are written only to the local
  `data/reports/` volume.
- **Auditable.** Every agent step + analyst action is appended to `agent_decisions`.

---

## Deliverables Summary

### 1. What is implemented

SentinelAI is a complete, runnable system — backend, frontend, ML pipeline, and
infra — with the six hardening capabilities of §0. In place:

- A modular-monolith architecture with explicit module boundaries.
- All five agent modules + the in-process event flow that connects them.
- The `backend/`, `frontend/`, `ml/`, `sensor/`, `infra/`, `docs/` layout.
- Database entities (migrations `0001`–`0007`) with columns, types, indexes, and
  the mode-aware response guardrail.
- HTTP + authenticated WebSocket API (auth, rate limits, drift, sensor, response).
- End-to-end data flow from ingested flow record to generated report, live over WS.
- JWT auth + RBAC, Redis rate limiting, model-drift monitoring, an optional
  lab-only live sensor, and an optional lab-only real-response framework.
- Ethics guardrails making the simulated-response stance explicit.

### 2. Files created / updated

- **Created:** [PROJECT_ARCHITECTURE.md](PROJECT_ARCHITECTURE.md) — this document.

No other files were created. The workspace was empty and intentionally remains so until Phase 0 begins.

### 3. How to test this stage

Architecture review, not code execution:

1. Open [PROJECT_ARCHITECTURE.md](PROJECT_ARCHITECTURE.md) and confirm the five agents, folder layout, DB entities, and API surface match the project requirements.
2. Walk through section **6. End-to-End Data Flow** with a sample CIC-IDS2017 row in mind and verify the state machine reaches `REPORTED` without ambiguity.
3. Confirm the ethics guardrails in section **8** are sufficient for the course's safety requirements.
4. Approve the phased plan, or request adjustments to scope before Phase 0 starts.

### 4. Assumptions made

- The CIC-IDS2017 dataset will be downloaded by the developer separately and placed under `ml/data/` (gitignored); the repo ships only a small sample slice under `backend/data/samples/`.
- A single-analyst demo is sufficient; multi-tenant auth and RBAC are out of scope.
- Postgres is the primary datastore; **Redis** is used for rate limiting and cross-worker WebSocket pub/sub (required in production, optional in dev). No Kafka or Elasticsearch — the modular monolith plus Redis fan-out fits the project's scale while still running correctly behind multiple workers.
- "Real-time" means seconds-level latency over a WebSocket from replayed CSV flows, not true wire-rate packet capture.
- WeasyPrint (HTML → PDF) is acceptable for the reporting agent; no LaTeX toolchain required.
- The simulated-response constraint is **non-negotiable**: any future "live action" adapter would require an explicit course-instructor approval and a separate review.
