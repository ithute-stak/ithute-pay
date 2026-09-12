# Ithute Pay Bridge — Administrator Production Deployment

This runbook deploys the unified Ithute Pay Bridge image from GitHub Container Registry (GHCR) to a VPS using the canonical Ithute Pay production domains.

## Production topology

```text
                         Internet / HTTPS 443
                                  |
                              Host Nginx
          ________________________|________________________
         |                        |                        |
pay.ithute.co.ls        api.pay.ithute.co.ls    portal.pay.ithute.co.ls
Main product/admin       Public integration API   Partner/VCL test portal
Next.js :3001            FastAPI :8001             Next.js :3001
+ browser/BFF API        /api/v1, /docs, etc.     /portal only
                                                  + /api/v1/portal/* only
         \________________________|________________________/
                                  |
                       ithute-pay-bridge container
                         FastAPI + Next.js + Celery
                                  |
                           PostgreSQL + Redis
```

The three domains have different responsibilities:

- `https://pay.ithute.co.ls` — the Ithute Pay application and administrative UI. Central !thute Auth signs human users into this surface.
- `https://api.pay.ithute.co.ls` — the canonical public API for product consumers, SDKs, merchant applications and provider/API integrations.
- `https://portal.pay.ithute.co.ls` — the consumer testing portal used by VCL/partners to exercise sandbox capabilities such as C2B, B2C, B2B, queries, reversals, authorization/update flows and direct debit. It is not a super-admin portal.

The portal accepts only sandbox/test application keys (`ipb_test_...`). Live application keys are rejected. The portal hostname blocks `/dashboard` and does not proxy the generic administrative API surface.

## 1. Publish an immutable image

GitHub Actions publishes images such as:

```text
ghcr.io/<owner>/ithute-pay-bridge:latest
ghcr.io/<owner>/ithute-pay-bridge:<commit-sha>
```

Use the commit SHA tag for controlled production releases whenever practical.

## 2. DNS and TLS

Create DNS records for all three names so they resolve to the Ithute Pay reverse-proxy host:

```text
pay.ithute.co.ls
api.pay.ithute.co.ls
portal.pay.ithute.co.ls
```

Install valid TLS certificates for all three hostnames and redirect HTTP to HTTPS. Do not enable live merchant/provider credentials over plain HTTP.

## 3. Prepare the VPS directory

A source checkout is not required for ordinary image deployment.

```text
/opt/ithute-pay-bridge/
├── compose.yaml
└── .env
```

Protect the environment file:

```bash
chmod 600 /opt/ithute-pay-bridge/.env
```

## 4. Production environment

Start from `deploy/env/production.env.example` and replace every placeholder. The canonical public values are:

```env
ENVIRONMENT=production
DEBUG=false
EXPOSE_ERROR_DETAILS=false

PUBLIC_APP_URL=https://pay.ithute.co.ls
PUBLIC_API_URL=https://api.pay.ithute.co.ls
PORTAL_APP_URL=https://portal.pay.ithute.co.ls
CORS_ORIGINS=https://pay.ithute.co.ls,https://portal.pay.ithute.co.ls
TRUSTED_HOSTS=pay.ithute.co.ls,api.pay.ithute.co.ls,portal.pay.ithute.co.ls,localhost,127.0.0.1
AUTH_COOKIE_SECURE=true
COOKIE_SAMESITE=lax
COOKIE_DOMAIN=

ITHUTE_AUTH_ENABLED=true
ITHUTE_AUTH_ISSUER=https://auth.ithute.co.ls
ITHUTE_AUTH_AUDIENCE=ithute-pay
ITHUTE_AUTH_JWKS_URL=https://auth.ithute.co.ls/.well-known/jwks.json
ITHUTE_AUTH_REDIRECT_URI=https://pay.ithute.co.ls/api/v1/auth/ithute/callback

ITHUTE_PUSH_ENABLED=true
ITHUTE_PUSH_URL=https://push.ithute.co.ls
ITHUTE_PUSH_SERVICE_CLIENT_SECRET=<runtime-only-secret>
```

Keep `COOKIE_DOMAIN` blank so human dashboard cookies remain host-scoped to `pay.ithute.co.ls`. The partner portal uses sandbox application API keys instead of the human dashboard session.

Central Auth must allowlist the exact callback `https://pay.ithute.co.ls/api/v1/auth/ithute/callback`. Production secrets remain runtime-only and must never be committed.

## 5. Provider settings

Real-money M-Pesa remains separate from the partner sandbox portal. Example production provider settings are:

```env
MPESA_ENABLED=true
MPESA_MODE=live
MPESA_ENVIRONMENT=production
MPESA_MARKET=vodacomLES
MPESA_COUNTRY=LES
MPESA_CURRENCY=LSL
MPESA_SERVICE_PROVIDER_CODE=<provider-code>
MPESA_API_KEY=<provider-secret>
MPESA_PUBLIC_KEY=<provider-public-key>
MPESA_ORIGIN=https://api.pay.ithute.co.ls
```

Provider secrets and encryption keys must be delivered to the VPS through a secure channel. They are never exposed in the partner portal.

## 6. Authenticate to GHCR

When the image is private, use a GitHub token with package-read permission:

```bash
echo "$GHCR_TOKEN" | docker login ghcr.io -u <github-user> --password-stdin
```

Do not store the token in `compose.yaml`.

## 7. Pull and deploy

```bash
cd /opt/ithute-pay-bridge

docker compose up -d postgres redis
docker compose pull ithute-pay-bridge
docker compose up -d --force-recreate ithute-pay-bridge
```

Check the application locally before exposing it through Nginx:

```bash
docker compose ps
docker compose logs --tail=200 ithute-pay-bridge
curl http://127.0.0.1:8001/health
curl -I http://127.0.0.1:3001/
```

Do not use `docker compose down -v` for ordinary upgrades because `-v` removes persistent volumes.

## 8. Migration policy

`RUN_MIGRATIONS_ON_START=true` applies `alembic upgrade head` before the application processes start. For controlled releases:

1. back up PostgreSQL;
2. record the running image tag;
3. inspect the migration in the candidate release;
4. deploy during a maintenance window if needed;
5. validate the Alembic head and health after startup.

A migration failure should prevent the new application from becoming healthy.

## 9. Host Nginx

Only Nginx should be Internet-facing. Keep the application ports bound to loopback:

```text
127.0.0.1:3001 -> Next.js
127.0.0.1:8001 -> FastAPI
```

Use `deploy/nginx/host-paybridge.conf` as the routing reference. Its boundaries are:

```text
pay.ithute.co.ls
  /                    -> 127.0.0.1:3001
  browser/BFF /api/*   -> 127.0.0.1:8001

api.pay.ithute.co.ls
  /*                   -> 127.0.0.1:8001

portal.pay.ithute.co.ls
  /                    -> /portal
  /portal...           -> 127.0.0.1:3001
  /api/v1/portal/*     -> 127.0.0.1:8001
  /dashboard...        -> 404
  other /api/*         -> 404
```

Validate before reload:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

Your TLS tooling may add `listen 443 ssl`, certificate paths and HTTP-to-HTTPS redirects around these routing blocks.

## 10. Partner/VCL testing portal

The partner portal intentionally models a consumer integration rather than platform administration.

1. Create a merchant and a `test` application through the administrator UI.
2. Issue an `ipb_test_...` API key for that application and transfer it securely to the VCL/partner tester.
3. The tester opens `https://portal.pay.ithute.co.ls` and enters the sandbox key.
4. The portal shows only the merchant/application context and supported sandbox test products.
5. The tester can exercise C2B, B2C, B2B, query status, reversal, transaction update/authorization and direct-debit test cases supported by the configured M-Pesa sandbox.
6. Each run is audited against the merchant application/API key.
7. `ipb_live_...` keys are rejected by the portal.

The portal never exposes platform provider credentials, merchant administration, fee configuration, settlement administration or super-admin controls.

## 11. Go-live workflow

1. Run the built-in administrator simulator/certification suite.
2. Create a merchant test application and complete consumer UAT through `portal.pay.ithute.co.ls`.
3. Confirm webhook signature verification and idempotency behavior through the public API.
4. Confirm accounting trial balance and reconciliation from the administrator surface.
5. Create a separate `live` application.
6. Configure approved live provider credentials server-side.
7. Generate a live API key and transfer it securely to the consumer application.
8. Perform one controlled low-value live transaction through `api.pay.ithute.co.ls`.
9. Confirm provider status, webhook delivery, accounting entry and consumer reconciliation.
10. Monitor errors and provider response codes during the initial production window.

## Production release checklist

- DNS resolves for all three canonical domains
- valid TLS certificate is installed for all three domains
- PostgreSQL backup verified
- GHCR image digest/tag recorded
- secrets are not in source control
- Nginx configuration test passes
- migrations complete
- application container healthy
- `https://api.pay.ithute.co.ls/health` passes
- `https://pay.ithute.co.ls` serves the main product UI
- `https://portal.pay.ithute.co.ls` serves the consumer portal and blocks `/dashboard`
- a sandbox `ipb_test_` key can run C2B/B2C/B2B test scenarios
- a live key cannot access the partner portal
