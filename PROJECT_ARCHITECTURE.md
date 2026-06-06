# SentinelAI — Project Architecture

**AI-Driven Intrusion Detection and Response Dashboard**

Term project for a third-year Computer and Network Security course. The system ingests network flow records, detects suspicious traffic with a CIC-IDS2017-trained classifier, and walks each alert through a five-stage agent workflow (Detect → Triage → Respond → Investigate → Report). All "response" actions are **simulated**: no real firewall, host, or third-party system is ever touched.

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

Each agent is a **plain Python class** under `backend/app/agents/`. They communicate through an in-process event bus (`core/events.py`) and share state via the database. No external orchestrator is needed at this scale; the workflow is a deterministic state machine driven by alert status transitions.

**Workflow state machine:**

```
NEW → TRIAGED → {AUTO_RESPONDED | AWAITING_ANALYST} → INVESTIGATED → REPORTED → CLOSED
```

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

### 2.3 Response Agent — `agents/response.py` **(simulated only)**

- **Input:** `alert.triaged` event.
- **Job:** consult a policy table (`response_policies`) and propose an action:
  - `BLOCK_IP` (simulated),
  - `RATE_LIMIT` (simulated),
  - `ISOLATE_HOST` (simulated),
  - `NOTIFY_ANALYST` (always real — writes to UI),
  - `NO_ACTION`.
- For `LOW/MEDIUM` it sets status `AWAITING_ANALYST` and waits for a human to click "Approve" in the UI.
- For `HIGH/CRITICAL` it auto-executes the simulated action and sets status `AUTO_RESPONDED`.
- **Output:** creates a `ResponseAction` row with `executed=true|false` and `simulated=true` (always). Emits `alert.responded`.

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
│   │   │   ├── events.py            ← in-process pub/sub
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

## 7. Phased Implementation Plan

Each phase ends with a working, demoable state — no half-finished slices.

### Phase 0 — Scaffolding (½ day)
- Repo skeleton, `docker-compose.yml`, `.env.example`, README.
- Empty FastAPI app with `/healthz`, empty Vite app with a placeholder dashboard.
- Postgres container up, Alembic initialized.
- **Demo:** `docker compose up` → healthy backend, blank dashboard.

### Phase 1 — Data model & migrations (½ day)
- SQLAlchemy models for `alerts`, `response_actions`, `reports`, `assets`, `audit_log`.
- First Alembic migration. Seed script with a handful of assets.
- **Demo:** `psql` shows tables; `/api/v1/alerts` returns `[]`.

### Phase 2 — ML pipeline offline (1 day)
- `ml/preprocess.py`, `ml/train.py`, `ml/evaluate.py`.
- Train a baseline RandomForest on a CIC-IDS2017 sample, persist `model.joblib`, `scaler.joblib`, `metadata.json`.
- **Demo:** `python ml/train.py --sample` produces artifacts with > 0.95 macro-F1 on the held-out slice.

### Phase 3 — Detection + Triage agents + ingestion (1 day)
- `ingestion/parser.py`, `ingestion/replayer.py`, `POST /ingest/flow`.
- `agents/detection.py` loads model at startup, classifies a flow, writes Alert.
- `agents/triage.py` assigns severity.
- **Demo:** `POST /ingest/replay` walks through 200 flows; `GET /alerts` shows them with severity.

### Phase 4 — Response agent + WebSocket (1 day)
- `agents/response.py` with policy table and simulated execution.
- WebSocket broadcaster, frontend `useWS()` hook.
- **Demo:** Dashboard updates live as flows are replayed; Response Center lists pending approvals.

### Phase 5 — Frontend pages (1.5 days)
- Dashboard (KPIs + severity-over-time chart + recent alerts).
- Alerts list (filterable table) + Alert Detail (with Agent Timeline).
- Response Center (approve / reject).
- Reports list.
- **Demo:** Full UI navigable; approving an action moves the alert forward visibly.

### Phase 6 — Investigation + Reporting agents (1 day)
- `agents/investigation.py` builds the packet, surfaces in Alert Detail.
- `agents/reporting.py` produces per-alert markdown + PDF via WeasyPrint.
- Daily summary endpoint + cron tick (simple `asyncio.create_task` loop).
- **Demo:** Click an alert → see investigation block → "Generate Report" → PDF downloads.

### Phase 7 — Polish, tests, docs (1 day)
- pytest coverage on agents and API.
- Frontend smoke tests with Vitest.
- `docs/ETHICS.md`, `docs/DEMO_SCRIPT.md`, screenshots in `README.md`.
- **Demo:** End-to-end replay of an attack slice, narrated.

**Total: ~7 working days** — fits a term project sprint.

---

## 8. Ethics & Safety Guardrails

- **No live response.** Every `ResponseAction` has `simulated=true` enforced at the model layer; there is no adapter that reaches outside the container.
- **No real network capture in default mode.** The replayer reads from a CSV file shipped with the project; live capture is out of scope.
- **No external data exfiltration.** The reporting agent writes only to the local `data/reports/` volume.
- **Dataset license respected.** CIC-IDS2017 usage is documented in `docs/DATASET.md`; raw dataset files are gitignored.
- **Auditable.** Every transition and analyst action is appended to `audit_log`.

---

## Deliverables Summary

### 1. What was implemented (this stage)

This stage delivered the **architecture and planning artifact** for SentinelAI. No backend, frontend, or ML code has been written yet — that begins in Phase 0 of the implementation plan above. What is now in place:

- A concrete modular-monolith architecture with explicit module boundaries.
- Responsibilities defined for all five agent modules and the in-process event flow that connects them.
- A full folder layout for `backend/`, `frontend/`, `ml/`, `infra/`, and `docs/`.
- Database entities with columns, types, and indexes.
- HTTP + WebSocket API surface grouped by domain.
- End-to-end data flow from ingested flow record to generated report.
- A seven-phase implementation plan sized to a term project.
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
- Postgres is acceptable as the only datastore — no Redis, Kafka, or Elasticsearch — because the modular monolith and in-process event bus fit the project's scale.
- "Real-time" means seconds-level latency over a WebSocket from replayed CSV flows, not true wire-rate packet capture.
- WeasyPrint (HTML → PDF) is acceptable for the reporting agent; no LaTeX toolchain required.
- The simulated-response constraint is **non-negotiable**: any future "live action" adapter would require an explicit course-instructor approval and a separate review.
