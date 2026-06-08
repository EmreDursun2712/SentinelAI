# Backup & Disaster Recovery

SentinelAI's durable state is **PostgreSQL** (alerts, decisions, response
actions, reports, users/sessions, drift snapshots). Model artifacts live on disk
under `ml/artifacts/` and are reproducible via training. This doc covers backing
up and restoring the database, and the volume-wipe risks to avoid.

## What to back up

| Data | Where | Backup |
| --- | --- | --- |
| Database | `postgres_data` Docker volume | `pg_dump` (scripted below) |
| Model artifacts | `ml/artifacts/` (host bind mount) | Copy the dir, or retrain |
| Config/secrets | `.env` (git-ignored) | Store in your secret manager |

## Backup

The stack must be up. Writes a compressed SQL dump to `backups/` (git-ignored):

```bash
make backup-db
# or: bash infra/scripts/backup_db.sh
# custom location:
BACKUP_DIR=/mnt/backups bash infra/scripts/backup_db.sh
```

Each run produces `backups/sentinelai-<YYYYmmdd-HHMMSS>.sql.gz` via
`docker compose exec postgres pg_dump --clean --if-exists`. Automate it with cron:

```cron
# daily at 02:30, keep the script's output under /mnt/backups
30 2 * * *  cd /opt/sentinelai && BACKUP_DIR=/mnt/backups bash infra/scripts/backup_db.sh
```

Prune old dumps to taste, e.g. keep 14 days:

```bash
find /mnt/backups -name 'sentinelai-*.sql.gz' -mtime +14 -delete
```

## Restore

**Destructive** — the dump was made with `--clean --if-exists`, so it drops and
recreates objects, overwriting current data.

```bash
make restore-db BACKUP=backups/sentinelai-20260608-023000.sql.gz
# non-interactive (skip the confirmation prompt):
FORCE=1 bash infra/scripts/restore_db.sh backups/sentinelai-20260608-023000.sql.gz

# the schema includes everything; bounce the backend afterwards:
docker compose restart backend
```

If you restore into a *fresh* database, run migrations first so the schema
exists, or simply restore the full dump (it recreates the schema). After a
restore, verify:

```bash
curl -fsS localhost:8000/readyz | jq           # database: ok
docker compose exec backend alembic current    # at head
```

## ⚠️ Docker volume wipe risk

The database lives in the `postgres_data` Docker volume. These commands **erase
it** — there is no recovery without a backup:

- `make reset` → `docker compose down -v`
- `docker compose down -v` (the `-v` removes named volumes)
- `docker volume rm sentinelai_postgres_data`
- `docker system prune --volumes`

Safe operations that **keep** the volume: `make down` / `docker compose down`
(no `-v`), `docker compose restart`, `docker compose stop/start`.

> **Before any `-v` teardown on real data, run `make backup-db` first.**
> `make e2e` intentionally uses `down -v` for an isolated run — never point it at
> a database you care about.

## Disaster recovery checklist

```text
☐ Backups run on a schedule and land off-host (not just the app server)
☐ A restore has been test-run into a scratch stack (backups are verified)
☐ .env / secrets are recoverable from a secret manager
☐ Model artifacts are backed up or retrainable (python -m ml.train ...)
☐ Restore runbook: bring up stack → restore-db → restart backend → check /readyz
```
