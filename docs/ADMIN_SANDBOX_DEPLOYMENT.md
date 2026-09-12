# Ithute Pay Bridge — Administrator Sandbox Deployment

This runbook creates an isolated **test environment** for administrators, developers and consumer-integration teams. It uses the built-in provider simulator and must not contain production provider credentials.

## Goal

A successful sandbox deployment provides:

- the unified Ithute Pay Bridge application container;
- FastAPI on host loopback port `8001`;
- Next.js on host loopback port `3001`;
- Celery worker and beat inside the same application image;
- PostgreSQL and Redis as persistent supporting services;
- automatic Alembic migration at application startup;
- automatic creation of the initial platform administrator when no active super administrator exists;
- the admin **Sandbox test lab** with deterministic provider outcomes.

## 1. Prepare environment values

Create `.env` beside `compose.yaml` and keep it outside source control. A ready template is `deploy/env/sandbox.env.example`.

```env
ENVIRONMENT=development
DEBUG=true
EXPOSE_ERROR_DETAILS=true

DB_NAME=paybridge
DB_USER=paybridge
DB_PASSWORD=<sandbox-database-password>
REDIS_URL=redis://redis:6379/0

SECRET_KEY=<random-secret-at-least-32-chars>
DATA_ENCRYPTION_KEY=<different-random-secret>

PUBLIC_URL=http://localhost:8081
PUBLIC_APP_URL=http://localhost:8081
PUBLIC_API_URL=http://localhost:8081
CORS_ORIGINS=http://localhost:8081,http://localhost:3001
TRUSTED_HOSTS=localhost,127.0.0.1,testserver
AUTH_COOKIE_SECURE=false
COOKIE_SAMESITE=lax

RUN_MIGRATIONS_ON_START=true
AUTO_CREATE_PLATFORM_ADMIN=true
BOOTSTRAP_ADMIN_EMAIL=ithute.pay@itpay.co.ls
BOOTSTRAP_ADMIN_PASSWORD=<strong-sandbox-admin-password>
BOOTSTRAP_ADMIN_FULL_NAME=Ithute Pay Bridge Administrator

SANDBOX_TEST_LAB_ENABLED=true

MPESA_ENABLED=false
MPESA_MODE=simulator
MPESA_ENVIRONMENT=sandbox
MPESA_MARKET=vodacomLES
MPESA_COUNTRY=LES
MPESA_CURRENCY=LSL
```

Generate independent application secrets, for example:

```bash
python3 - <<'PY'
import secrets
print('SECRET_KEY=' + secrets.token_urlsafe(64))
print('DATA_ENCRYPTION_KEY=' + secrets.token_urlsafe(64))
PY
```

Do not reuse the database password as the dashboard administrator password.

## 2. Start persistent services

```bash
docker compose up -d postgres redis
docker compose ps
```

Wait until PostgreSQL and Redis are healthy.

## 3. Build and start Pay Bridge

```bash
docker compose up -d --build ithute-pay-bridge
```

The unified container applies Alembic migrations before starting FastAPI, Next.js, Celery worker and Celery beat.

Watch startup:

```bash
docker compose logs -f ithute-pay-bridge
```

## 4. Verify runtime health

```bash
curl http://127.0.0.1:8001/health
curl -I http://127.0.0.1:3001/
docker compose ps
```

Swagger is available from FastAPI at `/docs` when routed through the development reverse proxy.

## 5. Sign in as the initial platform administrator

When the users table has no active `platform_super_admin`, startup creates the administrator configured by `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD`.

The startup check is idempotent:

- an existing active super administrator is left unchanged;
- restarting the server does not create duplicate administrators;
- an existing configured email can be activated/promoted when no super administrator exists;
- the existing password is not overwritten on each restart.

## 6. Create a consumer test application

In the dashboard:

1. create or select a **Merchant**;
2. create an **Application** with environment `test`;
3. create an API key and securely save the returned `ipb_test_...` secret;
4. configure the merchant/application provider in sandbox/simulator mode;
5. create a test webhook endpoint when the consumer needs asynchronous events.

The full API key is shown only when it is created. Pay Bridge stores a hash afterward.

## 7. Run the built-in functional suite

Open **Dashboard → Sandbox test lab** and run **Run full success suite**.

The lab creates/reuses its own system-managed workspace and forces the M-Pesa adapter to `simulator`, regardless of other provider configurations.

Deterministic phone values:

```text
26658000001 -> success
26658000002 -> insufficient funds
26658000003 -> processing / unknown
```

The full suite validates collections, payouts, B2B transfers, two-stage authorization, direct debit, hosted checkout, payment links, reversal, settlement request, accounting balance, reconciliation and webhook signing.

## 8. Test consumer integrations

Give consumers only test credentials. Require them to validate:

- Bearer API-key authentication;
- `Idempotency-Key` behavior;
- successful collection flow;
- failed/insufficient-funds behavior;
- processing/unknown behavior;
- webhook HMAC verification;
- retry handling that reuses the same idempotency key;
- reconciliation of Pay Bridge IDs with their own business references.

## 9. Resetting sandbox data

Prefer creating a new test application or merchant rather than deleting accounting history. For a disposable local environment only, database volumes may be reset intentionally. Never apply destructive volume commands to a production deployment.

## Sandbox acceptance checklist

- PostgreSQL healthy
- Redis healthy
- unified application healthy
- migrations at current head
- admin login succeeds
- sandbox lab enabled
- full success suite passes
- failure scenario returns expected provider failure
- processing scenario remains pending rather than creating a duplicate transaction
- consumer webhook verifies a signed payload
- trial balance remains balanced
