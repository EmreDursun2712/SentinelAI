# All-in-one demo image.
#
# This image intentionally runs Postgres, the FastAPI backend, and the built
# React dashboard in one container so Docker Desktop shows SentinelAI as a
# single container. The existing per-service Dockerfiles are still available
# for the normal multi-container development workflow.

FROM node:20-alpine AS frontend-build

WORKDIR /src/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./

ARG VITE_API_BASE_URL=http://localhost:8000/api/v1
ARG VITE_WS_BASE_URL=ws://localhost:8000/api/v1
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
ENV VITE_WS_BASE_URL=${VITE_WS_BASE_URL}

RUN npm run build


FROM python:3.12-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    POSTGRES_USER=sentinelai \
    POSTGRES_PASSWORD=sentinelai \
    POSTGRES_DB=sentinelai \
    SENTINEL_ENV=development \
    SENTINEL_LOG_LEVEL=info \
    SENTINEL_DATABASE_URL=postgresql+psycopg://sentinelai:sentinelai@127.0.0.1:5432/sentinelai \
    SENTINEL_API_KEY=dev-api-key-change-me \
    SENTINEL_JWT_SECRET=dev-jwt-secret-change-me \
    SENTINEL_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173 \
    SENTINEL_ML_ARTIFACTS_DIR=/app/ml/artifacts \
    SENTINEL_INGEST_DATA_DIR=/app/backend/data \
    SENTINEL_REPORTS_DIR=/app/backend/data/reports

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        bash \
        build-essential \
        ca-certificates \
        curl \
        libpq-dev \
        postgresql \
        postgresql-client \
        postgresql-contrib \
 && rm -rf /var/lib/apt/lists/*

COPY backend/ /app/backend/
COPY ml/ /app/ml/
COPY infra/ /app/infra/

RUN python -m pip install --upgrade pip \
 && python -m pip install -e /app/backend \
 && python -m pip install -e /app/ml \
 && cd /app && python -m ml.train --synthetic 50000 \
 && chmod +x /app/infra/single-container/entrypoint.sh

COPY --from=frontend-build /src/frontend/dist /app/frontend_dist

EXPOSE 5173 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=45s --retries=8 \
    CMD curl -fsS http://localhost:8000/health >/dev/null \
     && curl -fsS http://localhost:5173/ >/dev/null \
     || exit 1

ENTRYPOINT ["/app/infra/single-container/entrypoint.sh"]
