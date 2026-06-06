FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System deps:
# - build-essential + libpq-dev: psycopg/sqlalchemy C extensions
# - curl: used by the container HEALTHCHECK below
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
 && rm -rf /var/lib/apt/lists/*

# Install Python deps first so that source-only edits don't bust the layer cache.
COPY pyproject.toml ./
RUN pip install -e ".[dev]"

# Copy source. The bind-mount in docker-compose overlays this in dev so live
# edits survive without rebuilding the image.
COPY . .

# Entrypoint: alembic upgrade head → exec uvicorn (see entrypoint.sh).
# CMD is the extra-args list forwarded to uvicorn (e.g. ["--reload"] from compose).
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=5 \
    CMD curl -fsS http://localhost:8000/health || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
CMD []
