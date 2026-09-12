# Ithute Pay

Ithute Pay is the centralized payment and payment-orchestration platform for **all Ithute Solutions products** and for **approved external/public projects**. Consumer systems integrate with one Ithute Pay API instead of embedding provider credentials or duplicating M-Pesa, EcoCash, PayPal or future provider-specific logic in every project.

Ithute Pay owns the payment-provider boundary, routing, payment lifecycle, accounting records, reconciliation, settlements, webhooks, audit and sandbox certification. LoanHub is one consumer of the platform, not the platform's defining use case.

## Central consumer model

The existing `Merchant -> Application -> ApiKey` model is the canonical integration boundary.

- **Ithute-owned projects:** Ithute Solutions is the business/merchant boundary and each product is represented by its own test/live application, credentials, scopes, webhooks and transaction namespace.
- **External/public projects:** each external organization is its own merchant and each of its systems is an application under that merchant.
- **Partner/VCL testing:** `portal.pay.ithute.co.ls` is a consumer testing portal using test application credentials. It is not a super-admin portal.
- **No direct provider duplication:** when Ithute Pay already supports a payment capability, new Ithute projects should integrate with Ithute Pay rather than implementing their own provider connection.

The stable platform contract is exposed at `GET /api/v1/platform`. The full architectural rule is documented in `docs/CENTRAL_PAYMENT_PLATFORM.md`.

## Public surfaces

- `https://pay.ithute.co.ls` — Ithute Pay management application.
- `https://api.pay.ithute.co.ls` — canonical API used by Ithute and external projects.
- `https://portal.pay.ithute.co.ls` — partner/VCL sandbox and certification portal.

## Architecture

- `apps/backend/` — FastAPI, SQLAlchemy, Alembic, provider integrations, Celery workers and payment services.
- `apps/frontend/` — Next.js management, consumer testing and public payment interfaces.
- `packages/sdk-python/` — Python client SDK.
- `packages/sdk-typescript/` — TypeScript client SDK.
- `deploy/` — Nginx, systemd, container and VPS deployment assets.
- `docs/` — central-platform, API, security, sandbox, deployment and integration guides.
- `compose.yaml` — local/sandbox stack with PostgreSQL, Redis, the unified application container and Nginx.

The unified application image runs FastAPI on port `8001`, Next.js on port `3001`, and the Celery worker/beat processes under the project supervisor. Nginx exposes the HTTP surfaces.

## !thute platform boundaries

Ithute Pay is a first-party `!thute Auth` client with client ID `ithute-pay`.

- Human identity comes from `https://auth.ithute.co.ls` using OpenID Connect Authorization Code + PKCE.
- Ithute Pay stores the immutable central `sub` in `users.auth_user_id`; email and phone are never used as cross-product identity keys.
- Ithute Pay still owns its own roles, merchant access, payment permissions, subscriptions and all business authorization.
- Existing local sign-in remains available behind `ITHUTE_AUTH_LEGACY_LOGIN_ENABLED` during migration. Users link the two identities only after proving both sessions; accounts are never linked just because emails look alike.
- Central access and refresh tokens stay in HttpOnly product cookies. The central Auth database, JWT private key, MFA secrets and passkey material are never copied into Ithute Pay.

Machine-to-machine payment requests use application-scoped Ithute Pay API keys (`ipb_test_...` and `ipb_live_...`). The historical prefix is retained for compatibility; it does not mean the service is LoanHub-specific or only a bridge. Signed requests, scopes and idempotency remain part of the payment-client security boundary.

Notifications use the separate `!thute Push` service.

- Device provider endpoints are registered with Push using a verified `ithute-pay` user access token.
- Server notifications use a short-lived central service token with `aud=ithute-push`, `azp=ithute-pay` and `scope=push.send`.
- FCM/APNs/Web-Push credentials, retry state and delivery receipts remain in the central Push service, not the Ithute Pay database.
- `POST /api/v1/notifications/test` provides a safe self-notification check once a user is linked and a central device endpoint exists.

Production activation requires an exact Ithute Pay callback URL in central Auth `AUTH_REDIRECT_URIS_JSON`, a unique runtime service secret in `AUTH_SERVICE_CLIENT_SECRETS_JSON`, and `ithute-pay` on the Push user/service allowlists. Real secrets must never be committed.

## Main capabilities

- Multi-tenant merchant/application isolation
- C2B / payment collections
- B2C / payouts
- B2B / transfers
- Transaction queries and refresh
- Reversals/refunds
- Hosted/public checkout and payment links
- Provider configuration and routing
- M-Pesa, EcoCash and PayPal provider adapters plus simulator/sandbox modes
- Mandates, authorizations and direct debit
- Fees, settlements and reconciliation
- Double-entry-oriented finance records
- Signed webhooks and idempotent requests
- Audit logs and realtime dashboard events
- Partner/VCL testing workspace
- Python and TypeScript SDKs
- Central !thute SSO and central Push integration

## Data ownership rule

Ithute Pay stores payment-domain data only. The consuming application continues to own its business-domain records.

For example, LoanHub keeps loans and borrowers, RSL POS keeps sales, Mailbox DNS keeps subscriptions/mail records, and an external merchant keeps its own customer/business data. Those systems send references and approved metadata to Ithute Pay and reconcile payment state through the API and signed webhooks.

Consumer projects must not connect directly to the Ithute Pay database or another consumer's data.

## Local sandbox

```bash
cp .env.example .env
# Replace every CHANGE_THIS / placeholder credential in .env.
docker compose up -d --build
```

The default public Docker endpoint is `http://localhost:8081`.

For local central SSO, register the exact callback `http://localhost:8081/api/v1/auth/ithute/callback` in the central Auth development configuration, set `ITHUTE_AUTH_ENABLED=true`, and keep `ITHUTE_AUTH_LEGACY_LOGIN_ENABLED=true` until existing users have linked their identities.

Do not run the stack with placeholder passwords or secrets. `compose.yaml` requires an explicit database password rather than silently supplying a production-unsafe fallback.

## Validation

The repository-level `.github/workflows/ithute-pay.yml` gate compiles the backend, runs authentication/central-integration and central-platform contract tests, and type-checks, lints and production-builds the Next.js frontend when Ithute Pay or its central Auth/Push contracts change. `VALIDATION_REPORT.md` records the earlier full product validation baseline; provider-specific and Playwright suites can still be run for deeper release testing.

## Production security boundary

Production credentials must remain server-side and must never be committed to the repository, bundled into Next.js, embedded in client applications or copied into public documentation. Use the authenticated provider configuration flow or deployment secret management.

Real-money provider activation is separate from simulator/sandbox functionality. Production operation requires the official provider application credentials, registered origins/callbacks, provider verification and any required approval or certification.

Review `docs/CENTRAL_PAYMENT_PLATFORM.md`, `docs/SECURITY.md`, `docs/ADMIN_PRODUCTION_DEPLOYMENT.md` and `docs/DEPLOYMENT.md` before a live deployment.

## LoanHub integration

LoanHub consumes Ithute Pay as one first-party payment client. It should not duplicate payment-provider credentials or provider-specific business logic inside the lending application. See `docs/LOANHUB_INTEGRATION.md` and `docs/GATEWAY_MIDDLEMAN_ARCHITECTURE.md` for the compatibility/integration details.
