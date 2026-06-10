# SentinelAI

> 🇬🇧 English below · 🇹🇷 **Türkçe için aşağı kaydırın** ([Türkçe README](#-sentinelai--türkçe))

AI-driven intrusion detection and response dashboard. Third-year Computer and Network Security term project.

A FastAPI backend, a React + TypeScript dashboard, a scikit-learn ML pipeline trained on CIC-IDS2017, and a five-agent workflow (Detect → Triage → Respond → Investigate → Report) — all wired together through PostgreSQL and Docker Compose. Response actions are **simulated only**; the system never touches a real firewall, host, or third-party service.

See [PROJECT_ARCHITECTURE.md](PROJECT_ARCHITECTURE.md) for the full design,
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for the deployment runbook, and
[docs/QUALITY.md](docs/QUALITY.md) for the test inventory and pre-demo checklist.
A Turkish, presentation-oriented "which file does what" guide is in
[docs/KOD_REHBERI.md](docs/KOD_REHBERI.md).

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
2. Builds and starts all services — `postgres`, `redis`, `backend`, `worker`,
   `frontend` (`docker compose up -d --build`).
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
| `make e2e`          | Full gate: up → train+stage model → smoke → `down -v`         |
| `make test`         | Backend pytest + frontend vitest                              |
| `make test-integration` | Real-Postgres backend tests (testcontainers; needs Docker) |
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

## Quality gates

CI runs on every push/PR; the same checks run locally via pre-commit. Full
detail in [docs/QUALITY.md](docs/QUALITY.md#3-continuous-integration-pre-commit--supply-chain).

**GitHub Actions** ([`.github/workflows/`](.github/workflows)):

| Workflow      | Checks                                                         |
| ------------- | ------------------------------------------------------------- |
| `backend`     | `ruff check` · `ruff format --check` · `pytest` (backend + sensor) + integration (real Postgres) |
| `frontend`    | `npm run typecheck` · `npm test` · `npm run build` + advisory Playwright e2e (full compose stack) |
| `security`    | `pip-audit` · `npm audit --audit-level=high` · CycloneDX SBOM |
| `e2e`         | `make e2e` (manual / weekly)                                  |

[Dependabot](.github/dependabot.yml) opens weekly grouped dependency PRs
(pip for backend/ml/sensor, npm for frontend, GitHub Actions).

**Local — run the checks before you push:**

```bash
# One-time: install the git hook
pip install pre-commit && pre-commit install

# Run every hook against the whole tree (ruff, secret scan, frontend tsc, …)
pre-commit run --all-files

# Or invoke the gates directly
cd backend && ruff check . && ruff format --check . && pytest -q
cd frontend && npm run typecheck && npm test

# Real-database tests (migrations + DB constraints/transactions; needs Docker)
cd backend && pytest -m integration        # or: make test-integration

# Dependency audit
cd backend && pip-audit                       # Python CVEs
cd frontend && npm audit --audit-level=high   # npm advisories (high+)
```

Ruff is pinned to `0.15.16` everywhere (backend/ml/sensor `pyproject.toml`,
CI, and pre-commit) so formatting is identical on every machine.

---

## Authentication

Short-lived **access tokens** (15 min, sent as `Authorization: Bearer`, held in
memory by the SPA) plus long-lived **refresh-token sessions** in an **httpOnly
Secure cookie** with server-side revocation. `POST /api/v1/auth/refresh` rotates
the refresh token; logout / deactivation revoke it. Cookie-authenticated
mutations are protected by **double-submit CSRF** (`sentinelai_csrf` cookie →
`X-CSRF-Token` header). No token is ever in `localStorage`. Public endpoints:
`POST /auth/login`, `POST /auth/refresh`, `/health`, `/readyz`, `/docs`, OpenAPI.

Authorization is method-based RBAC: reads need **VIEWER**+, mutations need
**ANALYST**+, user management needs **ADMIN** (`VIEWER < ANALYST < ADMIN`). Every
protected request re-checks `is_active` + token version against the DB, so a
deactivated or logged-out-everywhere user loses access immediately.

> **Localhost dev:** browsers drop `Secure` cookies over plain HTTP — set
> `SENTINEL_AUTH_COOKIE_SECURE=false` for non-HTTPS dev (Compose already does).
> Production keeps the secure default.

Create the first admin on startup by setting **both** env vars (no default user is
ever created):

```bash
# in .env (Compose) — or SENTINEL_BOOTSTRAP_ADMIN_* for a local backend run
BACKEND_BOOTSTRAP_ADMIN_USERNAME=admin
BACKEND_BOOTSTRAP_ADMIN_PASSWORD=<a-strong-password>
```

Then open <http://localhost:5173>, sign in, and operate the dashboard. Admins get
a **Users** page to create accounts (with live password-policy feedback). Full
flow, cookie / SameSite / CSRF behavior, and curl examples: [docs/AUTH.md](docs/AUTH.md).

## Security defaults

The shipped configuration is **safe by default** — a fresh clone cannot capture
packets, touch a real firewall, or expose itself:

| Default | Behavior |
| --- | --- |
| **Response = simulated** | Real (non-simulated) actions are *structurally impossible* outside LAB mode (Postgres CHECK). LAB is **off**. |
| **Lab response = off** | Needs `RESPONSE_ENABLED=true` + `MODE=lab` + a lab executor + allowlisted CIDRs + analyst approval; every effect is reversible. |
| **Live sensor = off** | Needs `SENSOR_ENABLED=true` + authorized CIDRs; reads flow **metadata only** (no NIC, no payloads). |
| **Data retention = off** | All `RETENTION_*_DAYS` default `0` (nothing deleted). Dry-run first. |
| **Auth = required** | Every `/api/v1` route needs auth (except login/refresh/telemetry/health/docs); RBAC `VIEWER < ANALYST < ADMIN`. |
| **Secrets fail closed** | The backend refuses to start in a production-like `SENTINEL_ENV` with the default JWT secret, or with `SameSite=None` cookies that aren't `Secure`. |
| **No default user** | An admin is created only when both bootstrap env vars are set; nothing is hardcoded. |
| **Redis required in prod** | Rate limiting, WebSocket fan-out, and the task queue all require Redis in production (fail closed). |

Rotate `BACKEND_API_KEY`, `BACKEND_JWT_SECRET`, and the bootstrap admin password
(all `change-me` placeholders) before any exposed deployment. Full posture:
[docs/DEPLOYMENT_SECURITY.md](docs/DEPLOYMENT_SECURITY.md) · [docs/ETHICS.md](docs/ETHICS.md).

## Security hardening

Defense-in-depth beyond auth (details in [docs/DEPLOYMENT_SECURITY.md](docs/DEPLOYMENT_SECURITY.md)
and [SECURITY.md](SECURITY.md)):

- **HTTP security headers** on every response — CSP, `X-Content-Type-Options`,
  `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, and HSTS in
  production.
- **Password policy** (≥12 chars, ≥3 of 4 categories, no username) enforced for
  bootstrap + admin-created users, mirrored client-side.
- **Account lockout** — 5 failed logins in 15 min locks an account for 15 min
  (`423` + `Retry-After`); separate from rate limiting; admin can unlock.
- **CORS allow-listing** — no `*` with credentials; unsafe config fails closed in
  production.
- **Secure cookies + TLS** — secure-cookie/`SameSite` rules enforced at startup;
  reverse-proxy (Nginx/Caddy) HTTPS examples in the deployment doc.
- **Dependency scanning** — `pip-audit` / `npm audit` in CI + weekly Dependabot.

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

## Observability & operations

- **Metrics** — Prometheus exposition at `GET /metrics` (no auth; restrict at the
  network in prod). HTTP requests/latency by route/status/method, active
  WebSocket connections, ingestion rows/jobs, detection runs/events/alerts,
  response actions by status/type, drift score/status. Labels are
  low-cardinality and carry no IDs/usernames/IPs.
- **Tracing** — OpenTelemetry, **opt-in + no-op by default**. `pip install -e
  ".[otel]"`, set `SENTINEL_OTEL_ENABLED=true` (+ `SENTINEL_OTEL_EXPORTER_OTLP_ENDPOINT`);
  instruments FastAPI, SQLAlchemy, and outbound httpx.
- **Logging** — structlog with a per-request `request_id` (echoed as
  `X-Request-ID`) and the authenticated `user`/`role` bound on protected
  requests. Secrets/tokens are never logged.
- **Readiness** — `GET /readyz` returns structured per-dependency status
  (database, redis, model) and `503` when a *required* dependency is down;
  `GET /health` stays a lightweight liveness probe. The dashboard Topbar shows
  Backend / Database / Redis / Model / Live pills.
- **Backup/DR** — `make backup-db` and `make restore-db BACKUP=…`
  (`pg_dump`/`psql`); volume-wipe risks and a DR checklist in
  [docs/BACKUP_DR.md](docs/BACKUP_DR.md).

## Async task queue

Long jobs (large detection batches, report generation, daily summary, drift
checks, retention cleanup, optional retrain) run on a **Redis-backed
[arq](https://arq-docs.helpmanual.io/) worker** instead of blocking the request
thread. POST to `/api/v1/tasks/*` → get a **task id** back immediately; track it
via `GET /api/v1/tasks/{id}` / `GET /api/v1/tasks` and live `task.updated`
WebSocket events. Status lives in the `tasks` table (`PENDING → RUNNING →
SUCCEEDED | FAILED | CANCELLED`, with progress + result). The dashboard **System**
page has a Background-tasks panel. The `worker` Docker Compose service runs it
(`arq app.worker.WorkerSettings`). Full detail: [docs/TASK_QUEUE.md](docs/TASK_QUEUE.md).

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

The full system is implemented — the five-agent workflow, the dashboard, the ML
pipeline, and Docker Compose — plus six production-grade hardening capabilities.
The unsafe ones are **off by default**:

| Capability | Default | Docs |
| --- | --- | --- |
| JWT authentication + RBAC | on (all `/api/v1`) | [docs/AUTH.md](docs/AUTH.md) |
| Redis rate limiting | on | [docs/RATE_LIMITING.md](docs/RATE_LIMITING.md) |
| Real-time WebSocket broadcasting | on | [docs/API.md](docs/API.md#event-stream-websocket) |
| Model drift monitoring | on | [docs/MODEL_DRIFT.md](docs/MODEL_DRIFT.md) |
| Live-flow sensor (Zeek/Suricata logs) | **off — lab only** | [docs/LIVE_SENSOR.md](docs/LIVE_SENSOR.md) |
| Lab-only real response | **off — simulated** | [docs/LAB_RESPONSE.md](docs/LAB_RESPONSE.md) |

`make bootstrap` brings a fresh clone to a working demo in one command; the
default configuration is fully simulated and cannot capture packets or touch a
real firewall.

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

Response actions are **simulated by default**. A PostgreSQL `CHECK`
(`ck_response_actions_simulated_unless_lab`) makes a real (non-simulated) row
*structurally impossible* outside explicit `LAB` mode. LAB mode (optional, off by
default) only permits a controlled, **allowlisted, analyst-approved, reversible**
effect on an authorized lab network — never production or external targets; see
[docs/LAB_RESPONSE.md](docs/LAB_RESPONSE.md). The optional live sensor reads flow
**metadata only** (never payloads), is off by default, and runs only against
explicitly authorized lab subnets. See [docs/ETHICS.md](docs/ETHICS.md).

---
---

# 🇹🇷 SentinelAI — Türkçe

Yapay zekâ destekli saldırı tespit ve müdahale paneli. Üçüncü sınıf Bilgisayar ve Ağ
Güvenliği dönem projesi.

Bir FastAPI backend, React + TypeScript kontrol paneli, CIC-IDS2017 üzerinde eğitilmiş bir
scikit-learn ML hattı ve beş ajanlı bir iş akışı (Tespit → Önceliklendirme → Müdahale →
Soruşturma → Raporlama) — hepsi PostgreSQL ve Docker Compose ile birbirine bağlı. Müdahale
aksiyonları **yalnızca simüledir**; sistem gerçek bir firewall'a, sunucuya veya üçüncü taraf
servise asla dokunmaz.

Tam tasarım için [PROJECT_ARCHITECTURE.md](PROJECT_ARCHITECTURE.md), dağıtım için
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md), test envanteri için
[docs/QUALITY.md](docs/QUALITY.md). "Hangi dosya ne yapar" Türkçe sunum rehberi:
[docs/KOD_REHBERI.md](docs/KOD_REHBERI.md).

## Depo yapısı

```
SentinelAI/
├── backend/      FastAPI uygulaması, SQLAlchemy modelleri, ajan modülleri, testler
├── frontend/     React + TypeScript + Vite kontrol paneli
├── ml/           Çevrimdışı eğitim hattı (CIC-IDS2017)
├── sensor/       Opsiyonel canlı akış sensörü (Zeek/Suricata log okuma, lab-only)
├── infra/        Postgres init, yardımcı betikler, ters-proxy yapılandırması
├── docs/         Mimari, etik, kalite, ajan kılavuzları
├── docker-compose.yml
├── Makefile
├── .env.example
└── PROJECT_ARCHITECTURE.md
```

## Önkoşullar

- Compose v2 ile Docker Desktop 4.x (veya Docker Engine 24+)
- Make (her kısayolun ham komutu da gösterilir)
- Smoke testi için `curl` ve `jq`
- Modeli host üzerinde eğitmek için Python 3.12 (bootstrap betiği `ml/.venv`'i otomatik kurar)

## Hızlı başlangıç — tek komut

```bash
make bootstrap
```

Bu tek hedef şunları yapar:

1. `.env` yoksa `.env.example` → `.env` kopyalar.
2. Tüm servisleri derleyip başlatır — `postgres`, `redis`, `backend`, `worker`, `frontend`
   (`docker compose up -d --build`).
3. `backend /health` yanıt verene kadar bekler.
4. `ml/artifacts/latest/` altında model yoksa `ml/.venv` oluşturur, 50 bin satırlık sentetik
   model eğitir ve artefaktları yazar.
5. Backend'i yeniden başlatır ve `/api/v1/detection/model` `loaded: true` raporlayana kadar bekler.

Bittiğinde kontrol paneli için <http://localhost:5173> adresini aç. Bootstrap'in oluşturduğu
admin (`.env` içindeki `BACKEND_BOOTSTRAP_ADMIN_*`) ile giriş yap.

Uyarılar, raporlar ve denetim izi ile doldurmak için:

```bash
make smoke           # bash infra/scripts/smoke_demo.sh
```

## Servisler

| Servis     | URL                                    | Not                            |
| ---------- | -------------------------------------- | ------------------------------ |
| `frontend` | http://localhost:5173                  | Vite geliştirme sunucusu (HMR) |
| `backend`  | http://localhost:8000                  | FastAPI; OpenAPI `/docs`       |
| `worker`   | —                                      | arq async görev işleyici       |
| `postgres` | `postgres://localhost:5432/sentinelai` | Kalıcı volume                  |
| `redis`    | `redis://localhost:6379/0`             | Limit + WS pub/sub + kuyruk    |

Sağlık probları:

```bash
curl http://localhost:8000/health                  # her zaman 200
curl http://localhost:8000/readyz                  # DB/Redis/kuyruk/model durumu (gerekli bağımlılık çökerse 503)
curl http://localhost:8000/api/v1/detection/model  # { "loaded": true, ... } (kimlik doğrulamalı)
```

## Make hedefleri

Canlı menü için `make help`. En sık kullanılanlar: `make bootstrap` (tek-komut kurulum),
`up` / `down` / `reset` (DB volume'unu siler), `logs` / `logs-backend`, `seed` (modeli
yeniden eğit), `smoke` (11 adımlı uçtan uca test), `e2e` (tam kapı), `test`
(backend pytest + frontend vitest), `test-integration` (gerçek Postgres),
`typecheck`, `lint`, `backup-db` / `restore-db`, `shell-db`.

## Yerel geliştirme (Docker'sız)

```bash
# Backend
cd backend && cp .env.example .env
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]" && alembic upgrade head && uvicorn app.main:app --reload

# Frontend
cd frontend && cp .env.example .env && npm install && npm run dev

# ML hattı
cd ml && python -m venv .venv && source .venv/bin/activate
pip install -e . && python -m ml.train --synthetic 50000
```

## Kalite kapıları

Her push/PR'da CI çalışır; aynı kontroller yerelde pre-commit ile koşar. Detay
[docs/QUALITY.md](docs/QUALITY.md). GitHub Actions iş akışları: `backend`
(ruff + pytest + gerçek-Postgres entegrasyon), `frontend` (typecheck + vitest + build +
advisory Playwright e2e), `security` (pip-audit + npm audit + CycloneDX SBOM), `e2e`
(haftalık). [Dependabot](.github/dependabot.yml) haftalık bağımlılık PR'ları açar.

```bash
# Push'tan önce yerelde:
pip install pre-commit && pre-commit install
pre-commit run --all-files
cd backend && ruff check . && ruff format --check . && pytest -q
cd frontend && npm run typecheck && npm test
```

Ruff her yerde `0.15.16`'ya sabitlenmiştir (her makinede aynı biçimlendirme).

## Kimlik doğrulama

Kısa ömürlü **erişim token'ları** (15 dk, `Authorization: Bearer`, SPA tarafından bellekte
tutulur) artı **httpOnly Secure çerez** içindeki uzun ömürlü **refresh oturumları** (sunucu
tarafı iptal ile). `POST /api/v1/auth/refresh` refresh token'ı döndürür; logout/pasifleştirme
iptal eder. Çerezle kimlik doğrulanan mutasyonlar **çift-gönderim CSRF** ile korunur
(`sentinelai_csrf` çerezi → `X-CSRF-Token` başlığı). **Hiçbir token `localStorage`'da
tutulmaz.** Public uçlar: `POST /auth/login`, `POST /auth/refresh`, `/health`, `/readyz`,
`/docs`, OpenAPI.

Yetkilendirme metot tabanlı RBAC'tır: okuma **VIEWER**+, mutasyon **ANALYST**+, kullanıcı
yönetimi **ADMIN** (`VIEWER < ANALYST < ADMIN`). Her korumalı istek `is_active` + token
sürümünü DB'ye karşı yeniden kontrol eder; pasifleştirilen veya her yerden çıkış yapan
kullanıcı erişimini anında kaybeder.

> **Yerel geliştirme:** Tarayıcılar düz HTTP üzerinde `Secure` çerezleri düşürür —
> HTTPS olmayan geliştirmede `SENTINEL_AUTH_COOKIE_SECURE=false` ayarla (Compose zaten yapar).
> Üretim güvenli varsayılanı korur.

İlk admin başlangıçta **her iki** env değişkeni de ayarlıysa oluşturulur (asla varsayılan
kullanıcı yaratılmaz). Tam akış ve curl örnekleri: [docs/AUTH.md](docs/AUTH.md).

## Güvenlik varsayılanları

Gönderilen yapılandırma **varsayılan olarak güvenlidir** — taze bir klon paket yakalayamaz,
gerçek bir firewall'a dokunamaz veya kendini dışa açamaz:

| Varsayılan | Davranış |
| --- | --- |
| **Müdahale = simüle** | Gerçek (simüle-olmayan) aksiyon LAB modu dışında *yapısal olarak imkânsız* (Postgres CHECK). LAB **kapalı**. |
| **Lab müdahale = kapalı** | `RESPONSE_ENABLED=true` + `MODE=lab` + lab yürütücü + izinli CIDR + analist onayı gerektirir; her etki geri alınabilir. |
| **Canlı sensör = kapalı** | `SENSOR_ENABLED=true` + izinli CIDR gerektirir; yalnız akış **metadatası** okur (NIC yok, payload yok). |
| **Veri saklama = kapalı** | Tüm `RETENTION_*_DAYS` varsayılan `0` (hiçbir şey silinmez). Önce dry-run. |
| **Auth = zorunlu** | Her `/api/v1` ucu kimlik ister (login/refresh/telemetry/health/docs hariç); RBAC. |
| **Sırlar fail-closed** | Backend, üretim benzeri ortamda varsayılan JWT sırrı ile başlamayı reddeder. |
| **Varsayılan kullanıcı yok** | Admin yalnız iki bootstrap env'i de ayarlıysa oluşturulur; hiçbir şey gömülü değil. |
| **Üretimde Redis zorunlu** | Hız limiti, WS yayını ve görev kuyruğu üretimde Redis gerektirir (fail-closed). |

Açık bir dağıtımdan önce `BACKEND_API_KEY`, `BACKEND_JWT_SECRET` ve bootstrap admin
parolasını (hepsi `change-me`) döndürün. Detay: [docs/DEPLOYMENT_SECURITY.md](docs/DEPLOYMENT_SECURITY.md).

## Güvenlik sertleştirme

Auth ötesinde derinlemesine savunma: her yanıtta **HTTP güvenlik başlıkları** (CSP, nosniff,
frame-deny, Referrer/Permissions-Policy, üretimde HSTS); **parola politikası** (≥12 karakter,
4 kategoriden ≥3'ü, kullanıcı adı içermez); **hesap kilidi** (15 dk'da 5 başarısız → 15 dk
kilit); **CORS izin listeleme** (kimlik bilgisiyle `*` yok); **güvenli çerez + TLS**;
**bağımlılık taraması** (CI'da pip-audit / npm audit + Dependabot).

## Hız sınırlama

Tüm API trafiği **Redis** destekli (kayan pencere, replikalar arası paylaşımlı) sınırlanır.
Kimlik doğrulananlarda kullanıcı başına, login'de IP+kullanıcı başına anahtarlanır. Limit
aşımında `Retry-After` başlığıyla **HTTP 429**. Varsayılanlar (`SENTINEL_RATE_LIMIT_*` ile
ayarlanır): login 5/dk, genel kimlikli 120/dk, ingest 10/dk, detection 5/dk, rapor 20/dk,
yanıt 60/dk. Üretimde Redis **zorunlu**; geliştirmede ulaşılamazsa süreç-içi limiter'a düşer.

## Gözlemlenebilirlik ve operasyon

- **Metrikler** — `GET /metrics`'te Prometheus (HTTP gecikmesi, WS bağlantıları, ingest,
  detection, yanıt, drift). Etiketler düşük-kardinalite; ID/kullanıcı/IP taşımaz.
- **İzleme** — OpenTelemetry, opsiyonel + varsayılan no-op.
- **Loglama** — structlog, istek başına `request_id` + kimlikli kullanıcı/rol; sır loglanmaz.
- **Hazırlık** — `GET /readyz` bağımlılık başına yapısal durum (DB/Redis/kuyruk/model);
  `GET /health` hafif canlılık probu. Üst bar Backend/Database/Redis/Model/Live pillerini gösterir.
- **Yedek/DR** — `make backup-db` ve `make restore-db` ([docs/BACKUP_DR.md](docs/BACKUP_DR.md)).

## Asenkron görev kuyruğu

Uzun işler (büyük detection batch'leri, rapor, günlük özet, drift, retention, opsiyonel
retrain) istek thread'ini bloklamadan **Redis destekli [arq](https://arq-docs.helpmanual.io/)
worker**'ında çalışır. `/api/v1/tasks/*`'a POST → anında **task id**; `GET /api/v1/tasks/{id}`
ve canlı `task.updated` WebSocket olaylarıyla izlenir. Durum `tasks` tablosunda. `worker`
Compose servisi bunu çalıştırır. Detay: [docs/TASK_QUEUE.md](docs/TASK_QUEUE.md).

## Ortam değişkenleri

Her seviyede (`./`, `backend/`, `frontend/`) `.env.example` kopyalayıp ayarla. Kök `.env`
Compose tarafından, servis bazlı dosyalar yerel çalıştırmalarda kullanılır. Varsayılanlar
sınıf demosu için güvenlidir ama **açık bir dağıtımdan önce döndürülmelidir** —
`BACKEND_API_KEY`, `BACKEND_JWT_SECRET` ve bootstrap admin parolası `change-me` yer
tutucularıyla gelir. Backend, üretim benzeri `SENTINEL_ENV`'de JWT sırrı hâlâ varsayılanken
başlamayı reddeder.

## Proje durumu

Sistem tamamen uygulanmıştır — beş ajanlı iş akışı, kontrol paneli, ML hattı ve Docker Compose
— artı altı üretim seviyesi sertleştirme yeteneği. Riskli olanlar **varsayılan kapalıdır**:
JWT auth + RBAC (açık), Redis hız limiti (açık), gerçek-zamanlı WebSocket yayını (açık), model
drift izleme (açık), canlı sensör (**kapalı — lab-only**), lab-only gerçek müdahale
(**kapalı — simüle**). `make bootstrap` taze bir klonu tek komutla çalışır demoya getirir;
varsayılan yapılandırma tamamen simüledir ve paket yakalayamaz ya da gerçek bir firewall'a
dokunamaz.

## Canlı sensör (opsiyonel, lab-only)

Çevrimdışı CSV replay'in ötesinde, opsiyonel bir **log-okuyucu sensör** (`sensor/`), Zeek veya
Suricata'nın zaten ürettiği loglardan *gerçek* akış metadatasını `POST /api/v1/ingest/flows`
ucuna besleyebilir. Yalnız akış **metadatası** okur — NIC bağlama yok, paket yakalama yok,
payload yok — ve **varsayılan kapalıdır**. Açıkça etkinleştirilip yetkili lab alt ağlarına
kapsamlandırılmadan çalışmaz. **Yalnızca sahibi olduğun veya izlemeye açıkça yetkili olduğun
ağlarda kullan.** Tam kılavuz: [docs/LIVE_SENSOR.md](docs/LIVE_SENSOR.md).

## Etik

Müdahale aksiyonları **varsayılan olarak simüledir**. Bir PostgreSQL `CHECK`
(`ck_response_actions_simulated_unless_lab`) gerçek (simüle-olmayan) bir satırı açık `LAB`
modu dışında *yapısal olarak imkânsız* kılar. LAB modu (opsiyonel, varsayılan kapalı) yalnızca
yetkili bir lab ağında **izin listesindeki, analist onaylı, geri alınabilir** bir etkiye izin
verir — asla üretim veya dış hedeflere değil; bkz. [docs/LAB_RESPONSE.md](docs/LAB_RESPONSE.md).
Opsiyonel canlı sensör yalnız akış **metadatası** okur (asla payload), varsayılan kapalıdır ve
yalnız açıkça yetkili lab alt ağlarına karşı çalışır. Bkz. [docs/ETHICS.md](docs/ETHICS.md).
