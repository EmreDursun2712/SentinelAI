# Deployment Security

How to run SentinelAI safely: TLS termination, HTTP security headers, secure
cookies, CORS, and the brute-force / password controls. The app ships secure
defaults for production and fails closed on unsafe configuration.

> Scope: this is a course project. The guidance below is "production-grade
> practical" — enough to deploy on a single host behind a reverse proxy.

---

## 1. TLS / reverse proxy (HTTPS termination)

Run the API (uvicorn) and the built frontend behind a reverse proxy that
terminates TLS. The proxy speaks HTTPS to the world and HTTP to the containers,
and forwards `X-Forwarded-Proto` so the app knows the original scheme.

Set the API to production mode so secure defaults engage:

```bash
SENTINEL_ENV=production
SENTINEL_JWT_SECRET=<32+ random bytes>      # app refuses to boot with the default
SENTINEL_AUTH_COOKIE_SECURE=true            # required in prod (enforced)
SENTINEL_CORS_ORIGINS=https://app.example.com
SENTINEL_REDIS_URL=redis://redis:6379/0     # required in prod
# If the frontend is a DIFFERENT site than the API:
# SENTINEL_AUTH_COOKIE_SAMESITE=none        # requires SECURE=true
```

### Nginx

```nginx
server {
    listen 443 ssl http2;
    server_name app.example.com;

    ssl_certificate     /etc/letsencrypt/live/app.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/app.example.com/privkey.pem;

    # HSTS at the edge (browsers only honor it over HTTPS).
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    # Static SPA (the built frontend). Set a CSP appropriate for the React app
    # here — the backend only governs the API/docs responses.
    location / {
        root /usr/share/nginx/html;
        try_files $uri /index.html;
        add_header X-Content-Type-Options "nosniff" always;
        add_header X-Frame-Options "DENY" always;
        add_header Referrer-Policy "no-referrer" always;
        add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self' https://app.example.com wss://app.example.com; frame-ancestors 'none'; base-uri 'none'; form-action 'self'" always;
    }

    # API + WebSocket → uvicorn. Forward the real scheme/host.
    location /api/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade           $http_upgrade;   # WebSocket /api/v1/stream
        proxy_set_header Connection        "upgrade";
    }
}

# Redirect plain HTTP → HTTPS.
server { listen 80; server_name app.example.com; return 308 https://$host$request_uri; }
```

### Caddy

Caddy provisions TLS automatically and sets sane defaults:

```caddy
app.example.com {
    encode gzip
    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options "nosniff"
        X-Frame-Options "DENY"
        Referrer-Policy "no-referrer"
    }
    handle /api/* {
        reverse_proxy backend:8000
    }
    handle {
        root * /usr/share/nginx/html
        try_files {path} /index.html
        file_server
    }
}
```

---

## 2. HTTP security headers (set by the backend)

`SecurityHeadersMiddleware` stamps every API/docs response (toggle with
`SENTINEL_SECURITY_HEADERS_ENABLED`):

| Header | Value |
| --- | --- |
| `Content-Security-Policy` | API: `default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'`. `/docs` + `/redoc` get a looser policy so Swagger UI/ReDoc load. |
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` (clickjacking; also `frame-ancestors 'none'` in CSP) |
| `Referrer-Policy` | `no-referrer` |
| `Permissions-Policy` | camera/mic/geolocation/usb/payment/… all disabled |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` — only when `hsts_active` (production, or `SENTINEL_SECURITY_HSTS_ENABLED=true`) |

The SPA is served by the frontend host, so set the SPA's CSP there (see the
Nginx block above). Enable HSTS only once TLS terminates in front — otherwise
the header is ignored anyway.

---

## 3. Secure cookies

| Cookie | Flags |
| --- | --- |
| `sentinelai_refresh` | `HttpOnly`, `Secure`*, `SameSite`, `Path=/api/v1/auth` |
| `sentinelai_csrf` | `Secure`*, `SameSite`, readable by JS (double-submit) |

\* `Secure` is controlled by `SENTINEL_AUTH_COOKIE_SECURE` (default **true**).
The app **refuses to start in production** if it is false, and refuses
`SameSite=none` without `Secure`. For local non-HTTPS dev set it to `false`
(browsers drop Secure cookies over `http://localhost`). Details in
[AUTH.md](AUTH.md).

---

## 4. CORS

`SENTINEL_CORS_ORIGINS` is a comma-separated allow-list of exact origins
(`scheme://host[:port]`, no path). Credentials are enabled, so:

- **No `*` with credentials** — rejected (fatal in production, warning in dev).
- Each origin is validated to be a bare origin; embedded wildcards / paths are
  rejected.

Misconfiguration raises at startup in production (`SENTINEL_ENV=production`),
so an unsafe deploy fails closed instead of silently allowing it.

---

## 5. Brute-force & password controls

- **Rate limiting** (Redis sliding window): login is `5/min` per IP+username;
  other endpoints per user. See [API.md](API.md#rate-limiting).
- **Account lockout** (separate): `SENTINEL_LOGIN_MAX_FAILED_ATTEMPTS` failures
  within `SENTINEL_LOGIN_FAILED_WINDOW_MINUTES` lock the account for
  `SENTINEL_LOGIN_LOCKOUT_MINUTES` (`423 Locked` + `Retry-After`). Admin reset:
  `POST /api/v1/auth/users/{username}/unlock`.
- **Password policy** (enforced for bootstrap + admin-created users): ≥12 chars,
  ≥3 of {lowercase, uppercase, number, symbol}, must not contain the username.

---

## 6. Dependency & vulnerability scanning

CI (`.github/workflows/security.yml`) runs `pip-audit`, `npm audit` (fails on
high+), and a CycloneDX SBOM; Dependabot opens weekly update PRs. Run locally:

```bash
cd backend && pip-audit
cd frontend && npm audit --audit-level=high
```

Triage and handling guidance is in [../SECURITY.md](../SECURITY.md).

---

## 7. Observability endpoints

| Endpoint | Auth | Notes |
| --- | --- | --- |
| `GET /metrics` | none | Prometheus exposition. **Restrict at the network** (internal scrape target / proxy allow-list) — don't expose it publicly. Set `SENTINEL_METRICS_ENABLED=false` to disable. |
| `GET /readyz` | none | Structured dependency status (DB/Redis/model); `503` when a required dep is down. |
| `GET /health` | none | Liveness only. |

Do **not** proxy `/metrics` through the public vhost. In the Nginx example,
either omit it from the public `server` block or gate it:

```nginx
location = /metrics { allow 10.0.0.0/8; deny all; proxy_pass http://backend:8000; }
```

Tracing (OpenTelemetry) is opt-in and no-op unless `SENTINEL_OTEL_ENABLED=true`
with the `otel` extra installed and an OTLP endpoint configured.

## 8. Production checklist

```text
☐ SENTINEL_ENV=production
☐ SENTINEL_JWT_SECRET set to 32+ random bytes (not the default)
☐ SENTINEL_AUTH_COOKIE_SECURE=true  (and SAMESITE=none only if cross-site)
☐ SENTINEL_CORS_ORIGINS = exact frontend origin(s), no "*"
☐ SENTINEL_REDIS_URL reachable (rate limiting is required in prod)
☐ TLS terminating proxy in front; HTTP→HTTPS redirect
☐ HSTS active (auto in prod) once HTTPS is verified
☐ Bootstrap admin password meets the policy; rotated from the example
☐ /metrics not publicly exposed (network-restricted)
☐ Database backups scheduled + verified (see docs/BACKUP_DR.md)
☐ pip-audit / npm audit clean (or documented exceptions)
```
