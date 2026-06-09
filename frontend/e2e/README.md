# End-to-end tests (Playwright)

These specs drive the **real** app against a running stack: backend (with a
trained model + migrated DB) and the built frontend.

## Run locally

```bash
# 1. Bring the stack up (from the repo root) and train a model:
docker compose up -d --build
docker compose exec backend alembic upgrade head
python -m ml.train --synthetic 50000        # stage ml/artifacts/latest

# 2. Install browsers once:
cd frontend
npx playwright install --with-deps chromium

# 3a. Run against a dev/preview server Playwright starts itself
#     (backend must be reachable at VITE_API_BASE_URL):
npm run build
npm run test:e2e

# 3b. …or point at an already-running frontend:
PLAYWRIGHT_BASE_URL=http://localhost:5173 npm run test:e2e
```

Credentials default to the bundled bootstrap admin and can be overridden:

```bash
PLAYWRIGHT_USER=admin PLAYWRIGHT_PASSWORD='Sentinel-Demo-2026!' npm run test:e2e
```

## Flows covered

| Spec                  | Flow                                                            |
| --------------------- | -------------------------------------------------------------- |
| `login.spec.ts`       | login → dashboard; bad credentials; sign out                   |
| `workflow.spec.ts`    | replay sample → run detection → alerts visible                 |
| `response.spec.ts`    | approve a simulated action; LAB approval modal gating          |

Specs that depend on state not present in a fresh demo (e.g. a **real LAB**
action — LAB mode is off by default) `test.skip` themselves with a clear reason
rather than flake.
