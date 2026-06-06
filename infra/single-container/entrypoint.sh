#!/usr/bin/env bash
# Start the complete SentinelAI demo stack inside one container:
# Postgres -> Alembic migrations -> FastAPI backend -> static SPA server.

set -euo pipefail

PGDATA="${PGDATA:-/var/lib/postgresql/data}"
POSTGRES_USER="${POSTGRES_USER:-sentinelai}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-sentinelai}"
POSTGRES_DB="${POSTGRES_DB:-sentinelai}"

export SENTINEL_ENV="${SENTINEL_ENV:-development}"
export SENTINEL_LOG_LEVEL="${SENTINEL_LOG_LEVEL:-${BACKEND_LOG_LEVEL:-info}}"
export SENTINEL_API_KEY="${SENTINEL_API_KEY:-${BACKEND_API_KEY:-dev-api-key-change-me}}"
export SENTINEL_JWT_SECRET="${SENTINEL_JWT_SECRET:-${BACKEND_JWT_SECRET:-dev-jwt-secret-change-me}}"
export SENTINEL_CORS_ORIGINS="${SENTINEL_CORS_ORIGINS:-${BACKEND_CORS_ORIGINS:-http://localhost:5173,http://127.0.0.1:5173}}"
export SENTINEL_DATABASE_URL="${SENTINEL_DATABASE_URL:-postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:5432/${POSTGRES_DB}}"
export SENTINEL_ML_ARTIFACTS_DIR="${SENTINEL_ML_ARTIFACTS_DIR:-/app/ml/artifacts}"
export SENTINEL_INGEST_DATA_DIR="${SENTINEL_INGEST_DATA_DIR:-/app/backend/data}"
export SENTINEL_REPORTS_DIR="${SENTINEL_REPORTS_DIR:-/app/backend/data/reports}"

PG_BIN="$(dirname "$(find /usr/lib/postgresql -mindepth 2 -maxdepth 3 -type f -name initdb | sort | tail -n 1)")"
if [[ -z "${PG_BIN}" || ! -x "${PG_BIN}/postgres" ]]; then
    echo "[entrypoint] could not locate postgres binaries" >&2
    exit 1
fi

sql_literal() {
    printf "%s" "$1" | sed "s/'/''/g"
}

start_postgres() {
    mkdir -p "${PGDATA}" /var/run/postgresql
    chown -R postgres:postgres "${PGDATA}" /var/run/postgresql

    if [[ ! -s "${PGDATA}/PG_VERSION" ]]; then
        echo "[entrypoint] initializing postgres data directory..."
        runuser -u postgres -- "${PG_BIN}/initdb" \
            --pgdata="${PGDATA}" \
            --encoding=UTF8 \
            --locale=C \
            --auth-local=trust \
            --auth-host=scram-sha-256 >/dev/null
    fi

    echo "[entrypoint] starting postgres..."
    runuser -u postgres -- "${PG_BIN}/pg_ctl" \
        -D "${PGDATA}" \
        -o "-c listen_addresses=127.0.0.1 -p 5432" \
        -w start >/dev/null

    local role_sql pass_sql db_sql
    role_sql="$(sql_literal "${POSTGRES_USER}")"
    pass_sql="$(sql_literal "${POSTGRES_PASSWORD}")"
    db_sql="$(sql_literal "${POSTGRES_DB}")"

    runuser -u postgres -- psql --set=ON_ERROR_STOP=1 --dbname=postgres >/dev/null <<SQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${role_sql}') THEN
        EXECUTE format('CREATE ROLE %I LOGIN PASSWORD %L', '${role_sql}', '${pass_sql}');
    ELSE
        EXECUTE format('ALTER ROLE %I WITH PASSWORD %L', '${role_sql}', '${pass_sql}');
    END IF;
END
\$\$;

SELECT format('CREATE DATABASE %I OWNER %I', '${db_sql}', '${role_sql}')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = '${db_sql}')\gexec
SQL

    if [[ -f /app/infra/postgres/init.sql ]]; then
        runuser -u postgres -- psql --set=ON_ERROR_STOP=1 --dbname="${POSTGRES_DB}" \
            --file=/app/infra/postgres/init.sql >/dev/null
    fi
}

stop_postgres() {
    if [[ -s "${PGDATA}/PG_VERSION" ]]; then
        runuser -u postgres -- "${PG_BIN}/pg_ctl" -D "${PGDATA}" -m fast -w stop >/dev/null 2>&1 || true
    fi
}

pids=()
cleanup() {
    local status=$?
    trap - EXIT INT TERM
    for pid in "${pids[@]}"; do
        kill "${pid}" >/dev/null 2>&1 || true
    done
    stop_postgres
    exit "${status}"
}
trap cleanup EXIT INT TERM

start_postgres

echo "[entrypoint] applying database migrations..."
cd /app/backend
alembic upgrade head

echo "[entrypoint] starting backend on :8000..."
uvicorn app.main:app --host 0.0.0.0 --port 8000 &
pids+=("$!")

echo "[entrypoint] starting frontend on :5173..."
python /app/infra/single-container/spa_server.py /app/frontend_dist 5173 &
pids+=("$!")

echo "[entrypoint] SentinelAI is ready: http://localhost:5173"
wait -n "${pids[@]}"
