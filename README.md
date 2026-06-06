# SentinelAI

AI-driven intrusion detection and response dashboard. Third-year Computer and Network Security term project.

A FastAPI backend, a React + TypeScript dashboard, a scikit-learn ML pipeline trained on CIC-IDS2017, and a five-agent workflow (Detect → Triage → Respond → Investigate → Report) — all wired together through PostgreSQL and Docker Compose. Response actions are **simulated only**; the system never touches a real firewall, host, or third-party service.

See [PROJECT_ARCHITECTURE.md](PROJECT_ARCHITECTURE.md) for the full design and [docs/QUALITY.md](docs/QUALITY.md) for the test inventory and pre-demo checklist.

---

## Repository layout

```
SentinelAI/
├── backend/      FastAPI app, SQLAlchemy models, agent modules, tests
├── frontend/     React + TypeScript + Vite dashboard
├── ml/           Offline training pipeline (CIC-IDS2017)
├── sensor/       Optional live-flow sensor (Zeek/Suricata log tailing, lab-only)
├── infra/        Postgres init, helper scripts, reverse-proxy config
├── docs/         Architecture, ethics, quality, agent guides
├── docker-compose.yml
├── Makefile
├── .env.example
└── PROJECT_ARCHITECTURE.md
```

---

## Prerequisites

- Docker Desktop 4.x (or Docker Engine 24+) with Compose v2
- Make (every shortcut below also has the raw command shown)
- `curl` and `jq` (for the smoke test)
- For training the model on the host:
  - Python 3.12 (the bootstrap script creates `ml/.venv` automatically)

---

## Quick start — one command

```bash
make bootstrap
```

That single target:

1. Copies `.env.example` → `.env` if no `.env` exists.
2. Builds and starts all three containers (`docker compose up -d --build`).
3. Waits for `backend /health` to respond.
4. If no model is staged at `ml/artifacts/latest/`, creates `ml/.venv`,
   trains a synthetic 50k-row model, and writes the artifacts.
5. Restarts the backend so it picks up the model and waits for
   `/api/v1/detection/model` to report `loaded: true`.

When it finishes, open <http://localhost:5173> for the dashboard.

To populate it with alerts, reports, and a full audit trail:

```bash
make smoke           # bash infra/scripts/smoke_demo.sh
```

Behind the scenes, `bootstrap.sh` is just a thin wrapper — you can run the
equivalent commands by hand:

```bash
cp .env.example .env
docker compose up -d --build
bash infra/scripts/seed.sh        # only on first run, or after `make reset`
docker compose restart backend
bash infra/scripts/smoke_demo.sh
```

---

## Services

| Service    | URL                                    | Notes                          |
| ---------- | -------------------------------------- | ------------------------------ |
| `frontend` | http://localhost:5173                  | Vite dev server with HMR       |
| `backend`  | http://localhost:8000                  | FastAPI; OpenAPI at `/docs`    |
| `postgres` | `postgres://localhost:5432/sentinelai` | Bind-mounted volume            |
| `redis`    | `redis://localhost:6379/0`             | Rate-limit counters            |

Health probes:

```bash
curl http://localhost:8000/health                # always 200
curl http://localhost:8000/readyz                # 200 if DB reachable, else 503
curl http://localhost:8000/api/v1/detection/model  # { "loaded": true, ... }
```

---

## Make targets

Run `make help` for the live menu. Most common:

| Target              | What it does                                                  |
| ------------------- | ------------------------------------------------------------- |
| `make bootstrap`    | One-shot setup (build + wait for health + seed model)         |
| `make up`           | `docker compose up -d`                                        |
| `make down`         | `docker compose down`                                         |
| `make reset`        | `docker compose down -v && up -d` (wipes the DB volume)       |
| `make logs`         | Tail logs from all services                                   |
| `make logs-backend` | Tail backend logs only                                        |
| `make seed`         | Re-train the detection model and restart the backend         |
| `make smoke`        | Run the 11-step end-to-end smoke test                         |
| `make test`         | Backend pytest + frontend vitest                              |
| `make typecheck`    | `tsc --noEmit` on the frontend                                |
| `make lint`         | Ruff lint + format check on the backend                       |
| `make shell-db`     | Open a `psql` prompt against the dev database                 |

---

## Local development (without Docker)

### Backend

```bash
cd backend
cp .env.example .env
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload
```

Run the test suite:

```bash
cd backend
pytest
```

### Frontend

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

### ML pipeline (standalone)

```bash
cd ml
python -m venv .venv && source .venv/bin/activate
pip install -e .
python -m ml.train --synthetic 50000
```

---

## Authentication

Every `/api/v1` endpoint requires a JWT except `POST /api/v1/auth/login`
(`/health`, `/readyz`, `/docs`, and the OpenAPI schema stay public). Authorization
is method-based RBAC: reads need **VIEWER**+, mutations need **ANALYST**+, and user
management needs **ADMIN** (`VIEWER < ANALYST < ADMIN`).

Create the first admin on startup by setting **both** env vars (no default user is
ever created):

```bash
# in .env (Compose) — or SENTINEL_BOOTSTRAP_ADMIN_* for a local backend run
BACKEND_BOOTSTRAP_ADMIN_USERNAME=admin
BACKEND_BOOTSTRAP_ADMIN_PASSWORD=<a-strong-password>
```

Then open <http://localhost:5173>, sign in, and operate the dashboard. Additional
users are created by an admin via `POST /api/v1/auth/users`. Full flow and curl
examples: [docs/API.md](docs/API.md#authentication--roles).

## Rate limiting

All API traffic is rate limited, backed by **Redis** (sliding window, shared
across replicas). Limits are keyed per user when authenticated, and per
IP+username for login. Exceeding a limit returns **HTTP 429** with a
`Retry-After` header. Defaults (env-overridable via `SENTINEL_RATE_LIMIT_*`):

| Scope                                   | Default       | Key            |
| --------------------------------------- | ------------- | -------------- |
| `POST /auth/login`                      | 5 / minute    | IP + username  |
| General authenticated API               | 120 / minute  | user           |
| Ingestion (`/ingest/*`)                 | 10 / minute   | user           |
| Detection (`/detection/*`)              | 5 / minute    | user           |
| Report generation                       | 20 / minute   | user           |
| Response approve/reject/recommend       | 60 / minute   | user           |

In production Redis is **required** — the backend refuses to start without it.
In development, if Redis is unreachable it logs a warning and falls back to an
in-process limiter so the demo still runs. Set `SENTINEL_RATE_LIMIT_ENABLED=false`
to disable limiting entirely. Details: [docs/API.md](docs/API.md#rate-limiting).

## Environment variables

Copy `.env.example` at each level (`./`, `backend/`, `frontend/`) and adjust
as needed. The root `.env` is consumed by Docker Compose; the per-service
files are used during local non-Docker runs. The defaults in `.env.example`
are safe for classroom demos but **must be rotated before any exposed
deployment** — `BACKEND_API_KEY`, `BACKEND_JWT_SECRET`, and the bootstrap admin
password ship as `change-me` placeholders by design. The backend refuses to
start in a production-like `SENTINEL_ENV` while `JWT_SECRET` is still the default.

---

## Project status

Phases 0–13 complete (data model, ingestion, ML pipeline, five-agent
workflow, frontend dashboard + alert/response/report pages, end-to-end
integration, test coverage). Phase 14 (this pass) hardens Docker Compose
for classroom demo use: backend entrypoint auto-applies migrations, both
service containers have health probes, and `make bootstrap` brings a fresh
clone to a working demo in one command.

---

## Live sensor (optional, lab-only)

Beyond offline CSV replay, an optional **log-tailing sensor** (`sensor/`) can feed
*real* flow metadata from logs that Zeek or Suricata already produced, into the
batch endpoint `POST /api/v1/ingest/flows`. It reads flow **metadata only** — no
NIC binding, no packet capture, no payloads — and is **disabled by default**. It
refuses to run unless explicitly enabled and scoped to authorized lab subnets:

```bash
# .env: SENSOR_ENABLED=true, SENSOR_ALLOWED_CIDRS=..., SENSOR_API_TOKEN=<analyst JWT>
docker compose --profile sensor up sensor
```

**Use only on networks you own or are explicitly authorized to monitor.** Full
guide and safety model: [docs/LIVE_SENSOR.md](docs/LIVE_SENSOR.md).

## Ethics

Every `ResponseAction` row is hard-locked to `simulated = TRUE` by a
PostgreSQL `CHECK` constraint — the database itself refuses to store any
row marked otherwise. No code path attempts to contact a real firewall,
EDR, host agent, or third-party service. The optional live sensor reads flow
**metadata only** (never payloads), is off by default, and runs only against
explicitly authorized lab subnets. See [docs/ETHICS.md](docs/ETHICS.md).
