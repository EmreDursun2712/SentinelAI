#!/usr/bin/env bash
# Back up the SentinelAI Postgres database to a compressed SQL dump.
#
#   bash infra/scripts/backup_db.sh            # -> backups/sentinelai-<ts>.sql.gz
#   BACKUP_DIR=/mnt/backups bash infra/scripts/backup_db.sh
#
# Uses `docker compose exec postgres pg_dump`, so the stack must be up. The dump
# uses --clean --if-exists so it can be restored over an existing database.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../.." && pwd)
cd "${REPO_ROOT}"

DB_USER="${POSTGRES_USER:-sentinelai}"
DB_NAME="${POSTGRES_DB:-sentinelai}"
OUT_DIR="${BACKUP_DIR:-backups}"

mkdir -p "${OUT_DIR}"
timestamp=$(date +%Y%m%d-%H%M%S)
out_file="${OUT_DIR}/sentinelai-${timestamp}.sql.gz"

echo "==> Dumping database '${DB_NAME}' (user '${DB_USER}') -> ${out_file}"
# -T: no TTY (pipe-safe). pg_dump streams; gzip compresses on the host.
docker compose exec -T postgres pg_dump \
    -U "${DB_USER}" -d "${DB_NAME}" --clean --if-exists \
    | gzip >"${out_file}"

size=$(du -h "${out_file}" | cut -f1)
echo "==> Backup complete: ${out_file} (${size})"
