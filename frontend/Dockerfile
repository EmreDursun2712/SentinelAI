FROM node:20-alpine

WORKDIR /app

# curl is used by the container HEALTHCHECK; alpine ships busybox wget but
# explicit curl gives a consistent invocation across services.
RUN apk add --no-cache curl

# Deps first for cache friendliness.
# Prefer `npm ci` (deterministic, requires lockfile); fall back to `npm install`
# the first time the lockfile hasn't been committed yet.
COPY package.json package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

# Copy source. docker-compose overlays this with a bind-mount in dev so HMR
# picks up host edits without an image rebuild.
COPY . .

EXPOSE 5173

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=5 \
    CMD curl -fsS http://localhost:5173/ >/dev/null || exit 1

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
