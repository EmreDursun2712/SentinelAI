# External notifications

Beyond the in-app `NOTIFY_ANALYST` response action, SentinelAI can fan
high-signal alerts out to external channels — **Slack**, a **generic webhook**,
and/or **SMTP email**. It is **off by default** and every send is best-effort and
isolated (one channel failing never blocks the others or the request).

## When a notification fires

| Trigger | Condition |
| --- | --- |
| New alert | severity ≥ `SENTINEL_NOTIFY_MIN_SEVERITY` (default `HIGH`), right after triage |
| Analyst verdict | any alert an analyst marks **CONFIRMED** (always, regardless of severity) |

Nothing fires unless `SENTINEL_NOTIFICATIONS_ENABLED=true` **and** at least one
channel is configured.

## Delivery path

Dispatch runs on the **arq task queue** (`notify_task`) so the request thread
never blocks on an outbound Slack/SMTP call. If no worker/Redis is present (a
single-node dev run), the enqueue helper falls back to an in-process best-effort
send so the demo still notifies.

```
alert (HIGH+ / CONFIRMED) → notify_alert() → queue.enqueue("notify_task", payload)
                                              → worker → dispatch() → Slack / webhook / email
```

## Configuration

All via `SENTINEL_*` env (Compose maps `BACKEND_*` → `SENTINEL_*`; see
`.env.example`). Configure the **same** values on the backend **and** the worker.

| Env | Default | Notes |
| --- | --- | --- |
| `SENTINEL_NOTIFICATIONS_ENABLED` | `false` | master switch |
| `SENTINEL_NOTIFY_MIN_SEVERITY` | `HIGH` | `LOW`/`MEDIUM`/`HIGH`/`CRITICAL` |
| `SENTINEL_SLACK_WEBHOOK_URL` | — | Slack incoming-webhook URL |
| `SENTINEL_NOTIFY_WEBHOOK_URL` | — | generic JSON `POST` target |
| `SENTINEL_SMTP_HOST` / `_PORT` | — / `587` | email host |
| `SENTINEL_SMTP_USERNAME` / `_PASSWORD` | — | optional SMTP auth |
| `SENTINEL_SMTP_USE_TLS` | `true` | STARTTLS |
| `SENTINEL_SMTP_FROM` | — | sender; required for email |
| `SENTINEL_NOTIFY_EMAIL_TO` | — | comma-separated recipients |

A channel is "configured" only when its required fields are set (email needs
host + from + at least one recipient). The generic webhook receives the full JSON
payload: `{source, title, body, severity, alert_id, reason, fields}`.

## Example (Slack only)

```bash
# .env
BACKEND_NOTIFICATIONS_ENABLED=true
BACKEND_NOTIFY_MIN_SEVERITY=HIGH
BACKEND_SLACK_WEBHOOK_URL=https://hooks.slack.com/services/XXX/YYY/ZZZ
```

Then a HIGH/CRITICAL detection (or any CONFIRMED disposition) posts to Slack.
