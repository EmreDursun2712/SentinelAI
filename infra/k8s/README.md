# Kubernetes / Helm deployment

A Helm chart for running SentinelAI on Kubernetes — backend (HPA-scaled), the
arq worker, the frontend, a one-shot migration Job, and optional bundled
Postgres/Redis. Docker Compose remains the quickest path for a local demo; this
chart is the "real production" story.

```
infra/k8s/helm/sentinelai/
├── Chart.yaml
├── values.yaml
└── templates/
    ├── _helpers.tpl
    ├── configmap.yaml        # non-secret SENTINEL_* env
    ├── secret.yaml           # secret SENTINEL_* env (or use existingSecret)
    ├── migrate-job.yaml      # `alembic upgrade head` (pre-install/upgrade hook)
    ├── backend.yaml          # Deployment + Service + HPA
    ├── worker.yaml           # arq worker Deployment
    ├── frontend.yaml         # Deployment + Service
    ├── postgres.yaml         # StatefulSet + Service (postgres.enabled)
    ├── redis.yaml            # Deployment + Service (redis.enabled)
    ├── ingress.yaml          # host-based routing (ingress.enabled)
    └── NOTES.txt
```

## Quick start

```bash
# 1. Build + push images (or point values at your registry tags):
#    ghcr.io/<you>/sentinelai-backend:<tag>  and  sentinelai-frontend:<tag>

# 2. Lint + render to review the manifests:
helm lint infra/k8s/helm/sentinelai
helm template sentinelai infra/k8s/helm/sentinelai | less

# 3. Install (creates namespace-scoped resources):
helm upgrade --install sentinelai infra/k8s/helm/sentinelai \
  --namespace sentinelai --create-namespace \
  --set image.backend.tag=0.1.0 --set image.frontend.tag=0.1.0

# 4. Watch it come up (the migrate Job runs first):
kubectl -n sentinelai get pods -w
```

## Production notes

- **Secrets.** Never ship the placeholder `secrets:` values. Either set real
  values via `--set`/`-f`, or pre-create a Secret and set `existingSecret: my-secret`
  (it must carry the same `SENTINEL_*` keys). Rotate `SENTINEL_JWT_SECRET`,
  `SENTINEL_API_KEY`, and the bootstrap admin password.
- **Managed data stores.** For production, set `postgres.enabled=false` and
  `redis.enabled=false` and point `SENTINEL_DATABASE_URL` / `SENTINEL_REDIS_URL`
  at RDS/Cloud SQL and ElastiCache/Memorystore. The bundled Postgres StatefulSet
  is a single replica with no backups — fine for a lab, not for prod.
- **Migrations run once.** The backend image entrypoint would run `alembic
  upgrade head` on every replica; the chart bypasses it (`command: uvicorn …`)
  and runs migrations in a single pre-install/pre-upgrade Job instead.
- **Autoscaling.** `backend.autoscaling` drives a CPU HPA (metrics-server
  required). Disable it to pin `backend.replicaCount`.
- **Ingress.** Off by default. Enable it and set `ingress.host` (+ TLS secret) to
  route `/api`, `/health`, `/readyz`, `/docs` to the backend and everything else
  to the SPA.
- **Observability.** Backend pods carry `prometheus.io/scrape` annotations; a
  cluster Prometheus (or the Compose observability profile) can scrape `/metrics`.
  See [docs/OBSERVABILITY.md](../../docs/OBSERVABILITY.md).
