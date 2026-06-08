#!/usr/bin/env bash
# Restore the SentinelAI Postgres database from a dump made by backup_db.sh.
#
#   bash infra/scripts/restore_db.sh backups/sentinelai-<ts>.sql.gz
#   FORCE=1 bash infra/scripts/restore_db.sh <file>     # skip the confirmation
#
# DESTRUCTIVE: the dump was created with --clean --if-exists, so it drops and
# recreates objects, overwriting current data. The stack must be up.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../.." && pwd)
cd "${REPO_ROOT}"

BACKUP="${1:-${BACKUP:-}}"
if [[ -z "${BACKUP}" ]]; then
    echo "usage: restore_db.sh <backup.sql.gz>   (or BACKUP=<file>)" >&2
    exit 2
fi
if [[ ! -f "${BACKUP}" ]]; then
    echo "backup file not found: ${BACKUP}" >&2
    exit 1
fi

DB_USER="${POSTGRES_USER:-sentinelai}"
DB_NAME="${POSTGRES_DB:-sentinelai}"

if [[ "${FORCE:-0}" != "1" ]]; then
    echo "About to OVERWRITE database '${DB_NAME}' from '${BACKUP}'."
    read -r -p "Type 'yes' to continue: " reply
    [[ "${reply}" == "yes" ]] || { echo "Aborted."; exit 1; }
fi

echo "==> Restoring '${DB_NAME}' from ${BACKUP}"
# Decompress on the host and stream into psql inside the container.
if [[ "${BACKUP}" == *.gz ]]; then
    gunzip -c "${BACKUP}" | docker compose exec -T postgres psql -U "${DB_USER}" -d "${DB_NAME}"
else
    docker compose exec -T postgres psql -U "${DB_USER}" -d "${DB_NAME}" <"${BACKUP}"
fi

echo "==> Restore complete. Consider: docker compose restart backend"
