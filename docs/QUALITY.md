# Quality Engineering

The reliability budget for a term-project demo is "the in-class run works
without surprises." This document captures the test inventory, commands,
known weak points, and the pre-demo checklist that keeps that budget intact.

---

## 1. Test inventory

| Layer            | Files                            | Count | Needs DB | Needs FastAPI | Command                                                       |
| ---------------- | -------------------------------- | ----: | -------- | ------------- | ------------------------------------------------------------- |
| Backend models   | `tests/test_models.py`           |     5 |   no     |    no         | `pytest tests/test_models.py`                                 |
| Backend triage   | `tests/test_triage.py`           |    12 |   no     |    no         | `pytest tests/test_triage.py`                                 |
| Backend response | `tests/test_response.py`         |    16 |   no     |    no         | `pytest tests/test_response.py`                               |
| Backend ingest   | `tests/test_ingestion.py`        |    20 |   no     |    no         | `pytest tests/test_ingestion.py`                              |
| Backend investig | `tests/test_investigation.py`    |    16 |   no     |    no         | `pytest tests/test_investigation.py`                          |
| Backend report   | `tests/test_reporting.py`        |    27 |   no     |    no         | `pytest tests/test_reporting.py`                              |
| Backend detect   | `tests/test_detection.py`        |    11 |   no     |   **yes**     | `pytest tests/test_detection.py` (needs `pip install -e .[dev]`) |
| Backend API      | `tests/test_health.py`           |     6 | optional |   **yes**     | `pytest tests/test_health.py`                                 |
| Frontend unit    | `src/**/*.test.{ts,tsx}`         |    29 |   no     |    no         | `npm test`                                                    |
| End-to-end smoke | `infra/scripts/smoke_demo.sh`    |    11 |  **yes** |   **yes**     | `bash infra/scripts/smoke_demo.sh` (needs running stack)      |

**Totals**: 142 pure-Python backend tests + 29 frontend tests + 11 e2e checks.

### Running everything

```bash
# Backend (full)
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest

# Backend (pure subset — works without FastAPI installed locally)
pytest --noconftest tests/test_models.py tests/test_triage.py \
  tests/test_response.py tests/test_ingestion.py \
  tests/test_investigation.py tests/test_reporting.py

# Frontend
cd frontend
npm install
npm test
npm run typecheck

# End-to-end (requires docker compose + model staged)
bash infra/scripts/smoke_demo.sh
```

---

## 2. Lint + format

| Project   | Tool              | Check command                       | Auto-fix command                |
| --------- | ----------------- | ----------------------------------- | ------------------------------- |
| Backend   | `ruff` (lint)     | `ruff check .`                      | `ruff check --fix .`            |
| Backend   | `ruff` (format)   | `ruff format --check .`             | `ruff format .`                 |
| Frontend  | TypeScript        | `npx tsc --noEmit`                  | n/a (it's a typecheck)          |

`pyproject.toml` already configures ruff with the rule set the project uses:
`E, F, I, B, UP, SIM, RUF`. Ruff also handles import ordering (`I`) so a
single `ruff format .` pass keeps both style and imports consistent.

Frontend has ESLint listed as a dependency but no flat config file ships —
TypeScript's `tsc --noEmit` is the primary correctness gate; tests cover
behavior.

---

## 3. Pre-demo checklist

The five-minute sanity check before standing in front of a class. Each line
is a single shell or browser action.

```text
☐ docker compose ps                                              # all three services Up
☐ docker compose exec backend alembic current                    # alembic head = 0004_response_action_types
☐ curl -fsS localhost:8000/health | jq                           # status: ok
☐ curl -fsS localhost:8000/readyz | jq                           # db: ok
☐ curl -fsS localhost:8000/api/v1/detection/model | jq .loaded   # true
☐ open http://localhost:5173                                     # dashboard loads, both pills green
☐ bash infra/scripts/smoke_demo.sh                               # all 11 steps green
☐ docker compose exec postgres psql -U sentinelai -d sentinelai \
    -c "SELECT COUNT(*) FROM alerts;"                            # > 0 if smoke test ran
☐ /response page: pending queue renders                          # KPI cards non-zero
☐ /reports page: pretty markdown renders with tables             # at least one report visible
```

If any line fails, run `docker compose logs -f backend` and the
**Troubleshooting** section below.

### Reset between demos

```bash
docker compose down -v        # wipes the database volume (model artifacts on disk survive)
docker compose up -d
docker compose exec backend alembic upgrade head
docker compose restart backend   # picks up the existing model
```

---

## 4. Bug-risk review

A scan of the codebase for places where things can plausibly go wrong on the
demo day. Each item is tagged with severity for a course-project context.

### High — must monitor

- **Model–data feature mismatch.** The synthetic-trained model has 21
  features in `feature_order`. The bundled `sample_flows.csv` only carries 9
  of them. The pipeline's `SimpleImputer(median)` fills the rest with the
  training-set median, which biases predictions toward the BENIGN profile
  for ambiguous rows. *Mitigation*: in `ml.train`, prefer synthetic data
  with the same column set as the demo CSVs, or train with the actual
  CIC-IDS2017 columns.
- **Detection blocks the event loop on large batches.** Fixed in this
  pass — `predict_proba` is now offloaded via `asyncio.to_thread` in
  `detect_events`. For very large batches (≥ 50 k events) consider chunking.
- **Single Postgres instance, no backups.** `docker compose down -v` wipes
  everything. *Mitigation*: don't `-v` between the prep run and the live
  demo, or use `pg_dump` as a snapshot.

### Medium — surfaces under load or odd inputs

- **Rate limiting** is now Redis-backed (sliding window) on every endpoint —
  login (5/min per IP+username), a 120/min per-user fallback, and tighter
  buckets on ingest/detection/report/response. Returns 429 + `Retry-After`.
  In dev it falls back to an in-process limiter if Redis is down; in prod Redis
  is required. See [API.md](API.md#rate-limiting).
- **CSV parser is permissive.** It accepts wide column-name variants and
  drops sentinels (`NaN`, `Infinity`). Good for real-world CSVs, but it
  means subtly wrong files ingest with high "valid_rows" counts. The errors
  list at most surfaces 50 per response.
- **Auto-execute response actions are HTTP-visible but not undoable.** Once
  a `BLOCK_IP` row is marked `EXECUTED`, there's no "unblock" endpoint. The
  ethics-CHECK constraint means this is fine (nothing actually blocked),
  but the audit chain doesn't model reversals.
- **TanStack Query default retry = 1.** Frontend silently retries failed
  requests once. If the backend is flapping, the UI hides the first error.
- **Multi-analyst race**: two analysts approving the same `PENDING` action
  in different tabs both succeed; the second call returns the same EXECUTED
  state. The audit log gains two ANALYST rows. Considered acceptable for a
  single-analyst demo.
- **Investigation packets can be large** (up to 200 events × `features`
  JSONB). The frontend renders them inline. With a real CIC-IDS2017 replay
  (millions of rows) the bound becomes important — already capped, but
  monitor.

### Low — cosmetic or process-only

- **WebSocket `/stream`** broadcasts real domain events (alert/response/report/
  ingestion/detection lifecycle) to authenticated clients; the frontend
  `StreamProvider` invalidates the matching TanStack Query keys so the UI
  updates without waiting for polling. Auth is via a `?token=` JWT; events fire
  only after the DB commit succeeds. See [API.md](API.md#event-stream-websocket).
- **Hardcoded `ui-analyst` analyst id** in three frontend places. Find and
  replace when auth lands.
- **Frontend doesn't show a global toast on mutation success/failure.**
  Errors flash inline; some flows have no visual confirmation. Adequate for
  this project; trivial later.
- **Docker compose `restart: unless-stopped`** means hung containers don't
  recover automatically — `docker compose restart backend` is the manual
  fix.

### Already mitigated

- Ethics: `simulated=TRUE` is a DB CHECK (cannot be bypassed in code).
- Audit: every state change writes an `agent_decisions` row (incl. `close`,
  fixed in the integration pass).
- Idempotency: `close_alert` no-ops when already CLOSED — no duplicate audit rows.
- Investigation `404` is treated as a soft "no packet yet" — no retry storm.
- `disposition` partial-unique index ensures only one alert disposition per
  alert; status transitions never regress past `CLOSED`.

---

## 5. Suggested minimal improvements

In rough order of value vs. effort:

1. **Backend CI gate** — three lines in a GitHub Action:
   ```yaml
   - run: pip install -e ".[dev]" --no-cache-dir
   - run: ruff check . && ruff format --check .
   - run: pytest
   ```
2. **Frontend CI gate**:
   ```yaml
   - run: npm ci
   - run: npm run typecheck && npm test
   ```
3. **Wrap the smoke test in CI** behind a `make e2e` recipe that boots
   docker compose, runs the script, and tears down.
4. **Promote `/health` and `/readyz` to a basic liveness probe in CI** so
   a broken main branch is caught before the demo morning.
5. **Add a `pytest --tb=short -m "not integration"` marker** for splitting
   unit vs. integration when the project grows.
6. **Add a `pre-commit` config** with `ruff` + `prettier` hooks. Saves the
   "I forgot to format" PR comments.

---

## 6. Troubleshooting

| Symptom                                                   | Likely cause                                                          | Fix                                                                          |
| --------------------------------------------------------- | --------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| `/readyz` returns 503 with `db: down`                     | Postgres container not ready                                          | `docker compose logs postgres`, then `docker compose up -d postgres`         |
| `/detection/model` returns `loaded: false`                | Model artifact missing under `ml/artifacts/latest/`                  | `python -m ml.train --synthetic 50000 && docker compose restart backend`     |
| Smoke step 6 fails: "no alerts available"                 | Threshold too high or model misclassifying all sample rows as BENIGN  | Lower `SENTINEL_DETECTION_THRESHOLD` to 0.3, restart backend, re-run         |
| Frontend can't reach backend (CORS error in DevTools)     | `SENTINEL_CORS_ORIGINS` doesn't include the frontend origin           | Set `SENTINEL_CORS_ORIGINS=http://localhost:5173` in `.env`                  |
| Ingestion succeeds but `valid_rows = 0`                   | CSV missing `event_time` column or unrecognized timestamp format      | Check `docs/INGESTION.md` for the alias map                                  |
| Migration fails with "constraint already exists"          | Partial migration state from a prior run                              | `docker compose down -v` + `alembic upgrade head`                            |
| `pytest` errors on `pytest-asyncio` not found             | Dev deps not installed                                                | `pip install -e ".[dev]"`                                                    |
| `npm test` errors on jsdom not found                      | Dev deps not installed                                                | `npm install`                                                                |
