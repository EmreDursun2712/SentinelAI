# Deployment

How to run SentinelAI for a classroom demo (Docker Compose) and how to stand it up
in a production-like way (reverse proxy + TLS, persistent data, a worker, backups,
and observability). Security specifics — TLS config, headers, cookies, CORS — live
in **[DEPLOYMENT_SECURITY.md](DEPLOYMENT_SECURITY.md)**; this doc is the operational
runbook. Disaster recovery is in **[BACKUP_DR.md](BACKUP_DR.md)**.

> **Defaults are simulated and safe.** Out of the box nothing touches a real
> firewall, host, or network — see [ETHICS.md](ETHICS.md). The variables that could
> enable real effects (lab response, the live sensor, data retention) are **off by
> default** and called out below.

---

## 1. Docker Compose — development / demo

```bash
make bootstrap        # cp .env.example .env → build → wait for /health →
                      # train a synthetic model → restart backend → model loaded
open http://localhost:5173
```

Compose services (`docker-compose.yml`):

| Service    | Port  | Role                                                            |
| ---------- | ----- | -------------------------------------------------------------- |
| `postgres` | 5432  | PostgreSQL 16 — data in the `postgres_data` named volume.      |
| `redis`    | 6379  | Rate-limit counters, cross-worker WS pub/sub, the arq queue.   |
| `backend`  | 8000  | FastAPI (Uvicorn). Mounts `./ml/artifacts` read-only.          |
| `worker`   | —     | `arq app.worker.WorkerSettings` — runs long jobs.             |
| `frontend` | 5173  | Vite dev server (HMR).                                         |
| `sensor`   | —     | **Optional**, `--profile sensor`; lab-only log-tailer.        |

Common targets (`make help` for all): `up` / `down` / `ps` / `logs` /
`reset` (⚠ wipes the DB volume) / `shell-db` / `backup-db` / `restore-db`.

Sign in with the bootstrap admin you set in `.env`
(`BACKEND_BOOTSTRAP_ADMIN_USERNAME` / `BACKEND_BOOTSTRAP_ADMIN_PASSWORD`); the
admin is created on first startup only when both are set. See [AUTH.md](AUTH.md).

---

## 2. Production-like deployment

The same images run in production behind a TLS-terminating reverse proxy. Minimum
viable production topology:

```
            Internet ──HTTPS──▶ Nginx/Caddy (TLS) ──▶ backend:8000 (API + WS)
                                          └─────────▶ static frontend build (or :5173)
                            backend + worker ──▶ Postgres (persistent) + Redis (persistent)
```

### 2.1 Build the frontend for production

The dev Compose runs Vite's dev server. For production, build static assets and
serve them from the proxy (or a static host), pointing the SPA at the public API:

```bash
cd frontend
VITE_API_BASE_URL=https://soc.example.com/api/v1 \
VITE_WS_BASE_URL=wss://soc.example.com/api/v1 \
npm ci && npm run build           # → frontend/dist/
```

### 2.2 Reverse proxy + TLS termination

Terminate HTTPS at Nginx/Caddy and proxy `/api` (REST + the `/api/v1/stream`
WebSocket, which needs `Upgrade`/`Connection` headers) to the backend, serving the
static SPA for everything else. **Copy-paste Nginx and Caddy configs are in
[DEPLOYMENT_SECURITY.md §1](DEPLOYMENT_SECURITY.md).** Key points:

- Proxy WebSockets (`proxy_set_header Upgrade $http_upgrade; Connection "upgrade"`).
- Forward `X-Forwarded-For` / `X-Forwarded-Proto` (the app honors the first XFF hop
  for client IP / rate-limit keying).
- Redirect plain HTTP → HTTPS.

### 2.3 Required production settings

Set a production-like environment so the app fails closed on insecure config
(it refuses to boot with the default JWT secret, or with `SameSite=None` cookies
that aren't `Secure`):

```bash
SENTINEL_ENV=production
SENTINEL_JWT_SECRET=<openssl rand -hex 32>        # never the shipped default
SENTINEL_API_KEY=<rotate>
SENTINEL_CORS_ORIGINS=https://soc.example.com     # exact origins, no "*"
SENTINEL_AUTH_COOKIE_SECURE=true                  # HTTPS only
SENTINEL_AUTH_COOKIE_SAMESITE=lax                 # or "none" (then SECURE=true) if API and UI are different sites
SENTINEL_REDIS_URL=redis://redis:6379/0           # REQUIRED in prod (rate limit + WS + queue)
SENTINEL_SECURITY_HSTS_ENABLED=true               # TLS is in front
SENTINEL_BOOTSTRAP_ADMIN_USERNAME=admin
SENTINEL_BOOTSTRAP_ADMIN_PASSWORD=<strong; rotate after first login>
```

In production **Redis is required** — the backend refuses to start without it
(rate limiting, WebSocket fan-out, and the task queue all depend on it). Manage
secrets with your platform's secret store; never commit `.env`.

### 2.4 Migrations

Apply schema migrations on deploy (idempotent; tested up *and* down):

```bash
docker compose exec backend alembic upgrade head
```

---

## 3. Persistence

| Data | Where | Notes |
| --- | --- | --- |
| PostgreSQL | `postgres_data` named volume | The system of record. Back it up (§5). Survives `make down`; **`make reset` / `down -v` destroys it.** |
| Redis | ephemeral by default | Holds rate-limit counters + transient pub/sub + the queue. Losing it is non-fatal (counters reset, in-flight tasks may need re-enqueue). Enable AOF/RDB persistence if you want durable queue state. |
| Model artifacts | `./ml/artifacts` (mounted read-only) | Produced by `ml/train.py`. Ship a trained `latest/` with the deploy, or train into a persistent volume. |
| Reports | `backend/data/reports/` | Generated markdown reports; back up alongside the DB if you keep the files. |

The **worker** shares the same Postgres/Redis and the same read-only model mount,
so it serves the exact business logic as the API.

---

## 4. Observability

- **Metrics:** Prometheus exposition at `GET /metrics` (no auth — restrict at the
  network/proxy in prod). HTTP latency by route/status, WS connections, ingestion,
  detection, response, drift. Labels are low-cardinality (no IDs/usernames/IPs).
- **Tracing:** OpenTelemetry, opt-in. Install the `otel` extra and set
  `SENTINEL_OTEL_ENABLED=true` + `SENTINEL_OTEL_EXPORTER_OTLP_ENDPOINT`.
- **Logs:** structured JSON (structlog) with a per-request `request_id` (echoed as
  `X-Request-ID`) and the authenticated `user`/`role`; no secrets.
- **Readiness:** `GET /readyz` returns per-dependency status (database, redis,
  model) and `503` when a *required* dependency is down; `GET /health` is a
  lightweight liveness probe. The dashboard **System** page surfaces these.

---

## 5. Backups

```bash
make backup-db                       # pg_dump → infra/backups/<timestamp>.sql.gz
make restore-db BACKUP=infra/backups/<file>.sql.gz
```

Schedule `backup-db` (cron/systemd timer) and store backups off-box. Full
procedure, volume-wipe risks, and a recovery checklist: [BACKUP_DR.md](BACKUP_DR.md).

---

## 6. Optional / off-by-default subsystems

| Subsystem | Enable with | Guide |
| --- | --- | --- |
| **Lab-only real response** | `SENTINEL_RESPONSE_ENABLED=true` + `MODE=lab` + a lab executor + `ALLOWED_CIDRS` (+ analyst approval) | [LAB_RESPONSE.md](LAB_RESPONSE.md) |
| **Live sensor** | `--profile sensor`; `SENTINEL_SENSOR_ENABLED=true` + `ALLOWED_CIDRS` + analyst token | [LIVE_SENSOR.md](LIVE_SENSOR.md) |
| **Data retention** | `SENTINEL_RETENTION_{EVENTS,ALERTS,REPORTS}_DAYS` > 0 (0 = disabled) | [DATA_RETENTION.md](DATA_RETENTION.md) |
| **ML retrain task** | `SENTINEL_ML_RETRAIN_ENABLED=true` | [TASK_QUEUE.md](TASK_QUEUE.md) |

All four are **off by default**. Always `make backup-db` and
`make retention-dry-run` before enabling retention on real data.

---

## 7. Single-container option

For the simplest possible demo deploy, `make single-container` builds one image
(`sentinelai:single`) that serves the built SPA + API together
(`infra/single-container/`). It is a baked image — rebuild to pick up changes — and
still requires a reachable Postgres + Redis.
