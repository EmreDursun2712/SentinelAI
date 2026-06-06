#!/usr/bin/env sh
# Block until Postgres is accepting connections, then exec the given command.
# Usage: wait_for_db.sh <host> <port> -- <cmd> [args...]

set -eu

host="${1:?host required}"
port="${2:?port required}"
shift 2

# Drop the optional "--" separator.
if [ "${1:-}" = "--" ]; then
    shift
fi

echo "Waiting for postgres at ${host}:${port}..."
attempts=0
until nc -z "${host}" "${port}" 2>/dev/null; do
    attempts=$((attempts + 1))
    if [ "${attempts}" -gt 60 ]; then
        echo "Database did not become reachable in time." >&2
        exit 1
    fi
    sleep 1
done

echo "Postgres is up. Executing: $*"
exec "$@"
