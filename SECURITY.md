# Security Policy

SentinelAI is a university Computer & Network Security term project. It is built
defensively (simulated response only, lab-gated controls) but is **not** a
hardened commercial product. Treat it accordingly.

## Reporting a vulnerability

Please report security issues **privately** — do not open a public issue for an
unpatched vulnerability. Use GitHub's **"Report a vulnerability"** (Security →
Advisories) on the repository, or contact the maintainer directly. Include a
description, affected version/commit, and reproduction steps. We aim to
acknowledge within a few days (best-effort for a course project).

## Handling dependency vulnerabilities

Scanning is automated and also runnable locally.

| Where | What |
| --- | --- |
| CI `security.yml` | `pip-audit` (Python, informational), `npm audit --audit-level=high` (gating), CycloneDX SBOM artifact, weekly + on PR |
| Dependabot | Weekly grouped update PRs for pip (backend/ml/sensor), npm (frontend), GitHub Actions |
| Local | `cd backend && pip-audit` · `cd frontend && npm audit --audit-level=high` |

**Triage workflow when an advisory appears:**

1. **Assess severity & reachability.** Is the vulnerable code path actually used?
   Note CVSS and whether it is a direct or transitive dependency.
2. **Prefer the Dependabot PR.** Merge the bump if CI (backend + frontend +
   integration) stays green. For a manual fix, raise the pinned version in the
   relevant `pyproject.toml` / `package.json` and re-run the audit.
3. **Keep cross-pinned deps in lockstep.** `scikit-learn` and `ruff` are pinned
   identically across projects — bump them together (see Dependabot groups).
4. **If no fix is available**, decide: mitigate (config/usage change), or accept
   with a documented, time-boxed exception. Record the rationale in the PR.
5. **Re-run audits** and confirm `npm audit --audit-level=high` is clean (it
   gates CI). `pip-audit` is informational so upstream/transitive advisories
   outside our control don't block the board — review them, don't ignore them.

## Secrets & configuration

- Never commit real secrets. `.env` is git-ignored; only `*.env.example` ships.
- Rotate `SENTINEL_JWT_SECRET` and `SENTINEL_API_KEY` before any shared deploy —
  the backend refuses to start in production with the default JWT secret.
- Production cookie/CORS/TLS requirements are enforced at startup and documented
  in [docs/DEPLOYMENT_SECURITY.md](docs/DEPLOYMENT_SECURITY.md).

## Built-in protections (overview)

Auth (short-lived access tokens + httpOnly refresh sessions, rotation,
revocation, CSRF), per-account lockout + rate limiting, a password policy, HTTP
security headers, CORS allow-listing, and ethics-gated/simulated response. See
[docs/AUTH.md](docs/AUTH.md) and [docs/DEPLOYMENT_SECURITY.md](docs/DEPLOYMENT_SECURITY.md).
