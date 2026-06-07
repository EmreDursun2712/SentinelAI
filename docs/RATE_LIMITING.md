# Rate limiting

Every API endpoint is rate limited with a **Redis-backed sliding window**
(shared across backend replicas). Exceeding a limit returns **HTTP 429** with a
`Retry-After` header; each hit is logged with the request id and the user/IP.

## Keying

Buckets are keyed by **user** when authenticated, and by **IP+username** for the
login endpoint (throttling both password-spraying one account and many-account
attempts from one source).

## Default policies (env-overridable)

| Policy | Endpoints | Default | Key |
| --- | --- | --- | --- |
| `login` | `POST /auth/login` | 5 / minute | IP + username |
| `authenticated` | every `/api/v1` functional router (general fallback) | 120 / minute | user |
| `ingest` | `/ingest/upload`, `/ingest/replay`, `/ingest/flow`, `/ingest/flows` | 10 / minute | user |
| `detection` | `/detection/run`, `/detection/batch`, `/detection/events/{id}`, `/detection/predict`, `/detection/drift/run` | 5 / minute | user |
| `report` | `/alerts/{id}/report`, `/reports/daily/run` | 20 / minute | user |
| `response` | `/response/recommend/{id}`, `/response/{id}/approve|reject|rollback` | 60 / minute | user |

Expensive endpoints consume **both** their specific bucket and the general
`authenticated` bucket. Override any policy with the matching env var, e.g.
`SENTINEL_RATE_LIMIT_DETECTION=10/minute` (format `<count>/<second|minute|hour>`).

## 429 response

```http
HTTP/1.1 429 Too Many Requests
Retry-After: 23

{ "error": { "code": "rate_limited", "message": "Rate limit exceeded...",
             "details": { "retry_after": 23 } }, "request_id": "..." }
```

The frontend never retries 4xx (including 429): the TanStack Query client and the
API client both stop on client errors, and login shows a clear message.

## Backend & failure modes

| Env | Default | Notes |
| --- | --- | --- |
| `SENTINEL_REDIS_URL` | _(unset)_ | e.g. `redis://redis:6379/0`. |
| `SENTINEL_RATE_LIMIT_ENABLED` | `true` | Set `false` to disable entirely. |

* **Production** (`SENTINEL_ENV` ∈ production/staging): Redis is **required** —
  the backend refuses to start if it is unset or unreachable (fail closed).
* **Development**: if Redis is unreachable the backend logs a warning and falls
  back to an in-process limiter (per-worker) so the demo still runs.
* A Redis error *during* a request fails **open** (request allowed + warning) so
  a transient blip can't take the whole API down.

Implementation: `app/core/ratelimit.py` (atomic Lua sliding-window for Redis,
deque-based for in-process). Tests: `backend/tests/test_ratelimit.py`.
