# Data Retention & Soft Delete

SentinelAI can age out old data on a configurable policy. **It is off by default
— nothing is ever deleted or archived unless you explicitly set a retention
window.** Where audit matters (alerts, reports) it *soft-deletes* (archives)
rather than hard-deletes.

## Policy

| Data | Env (days; `0` = disabled) | Action | Why |
| --- | --- | --- | --- |
| `network_events` | `SENTINEL_RETENTION_EVENTS_DAYS` | **hard delete** | High-volume, reproducible; not individually audited. |
| `alerts` | `SENTINEL_RETENTION_ALERTS_DAYS` | **soft archive** (`archived_at`) | Preserve the audit trail; just hide from default views. |
| `incident_reports` | `SENTINEL_RETENTION_REPORTS_DAYS` | **soft archive** (`archived_at`) | Same — reports back investigations. |

A row is in scope when `created_at < now - days`. Each policy is independent; a
`0`/unset value skips it entirely.

### Soft delete vs hard delete

- **Alerts & reports** get an `archived_at` timestamp. Archived rows are
  **excluded from the default list endpoints** (`GET /api/v1/alerts`,
  `GET /api/v1/reports`) and their `X-Total-Count`, but remain in the database
  for audit/forensics. Nothing is destroyed.
- **Events** are hard-deleted (they're the bulk of the data and are
  reproducible from ingestion). The `alerts.event_id` FK is
  `ON DELETE SET NULL`, so an alert that referenced a pruned event keeps its row
  — `event_id` simply becomes `NULL`. The alert's own snapshot fields
  (src/dst/prediction/confidence) are denormalized onto the alert, so it stays
  meaningful without the event.

## Running it

**Dry-run first** (counts only, writes nothing):

```bash
make retention-dry-run            # docker compose exec backend python -m app.scripts.retention
# or locally:
cd backend && python -m app.scripts.retention
```

Apply it:

```bash
make retention-apply              # DESTRUCTIVE (events hard-deleted; alerts/reports archived)
# or: cd backend && python -m app.scripts.retention --apply
```

Both print a JSON summary:

```json
{
  "dry_run": true,
  "events":  { "enabled": true, "action": "hard_delete",  "days": 90, "matched": 1240, "affected": 0 },
  "alerts":  { "enabled": true, "action": "soft_archive", "days": 365, "matched": 12, "affected": 0 },
  "reports": { "enabled": false, "matched": 0, "affected": 0 }
}
```

`matched` = rows the policy targets; `affected` = rows actually changed (always
`0` on a dry run).

### On a schedule (worker)

Retention also runs through the async task queue — the `RETENTION_CLEANUP` task
applies the same policy (plus housekeeping: old terminal tasks + drift
snapshots) and honors a `dry_run` flag:

```bash
# admin only
curl -fsS -X POST localhost:8000/api/v1/tasks/retention-cleanup \
  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"days":90,"dry_run":true}'
```

Schedule it with cron / a scheduler hitting that endpoint, or `make retention-apply`
from a cron job on the host. See [TASK_QUEUE.md](TASK_QUEUE.md).

## Configuration summary

```bash
SENTINEL_RETENTION_EVENTS_DAYS=0    # e.g. 90  → delete events older than 90d
SENTINEL_RETENTION_ALERTS_DAYS=0    # e.g. 365 → archive alerts older than 365d
SENTINEL_RETENTION_REPORTS_DAYS=0   # e.g. 365 → archive reports older than 365d
```

> **Safety:** defaults are `0` (disabled). Always `make retention-dry-run`
> before enabling in an environment with real data, and take a backup
> (`make backup-db`, see [BACKUP_DR.md](BACKUP_DR.md)) before the first apply.
