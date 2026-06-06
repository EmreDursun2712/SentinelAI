FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install deps first for layer caching.
COPY pyproject.toml ./
COPY sentinelai_sensor ./sentinelai_sensor
RUN pip install -e .

# No NIC binding, no raw capture, no extra capabilities — this only reads flow
# logs from a mounted path and posts metadata over HTTP.
ENTRYPOINT ["python", "-m", "sentinelai_sensor"]
