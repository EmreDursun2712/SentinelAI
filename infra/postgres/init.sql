-- Postgres initialization. Runs once on first container start.
-- Schema migrations are managed by Alembic (Phase 1).

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

DO $$
BEGIN
    RAISE NOTICE 'SentinelAI database initialized.';
END $$;
