# Ithute Pay Bridge — Administrator Deployment Guide

Ithute Pay Bridge supports two clearly separated operational journeys:

- **Sandbox/testing:** test applications, deterministic simulator responses and no live provider traffic.
- **Production:** one GHCR application image, persistent PostgreSQL/Redis, HTTPS, live provider credentials and controlled release management.

Detailed runbooks:

- [`ADMIN_SANDBOX_DEPLOYMENT.md`](./ADMIN_SANDBOX_DEPLOYMENT.md)
- [`ADMIN_PRODUCTION_DEPLOYMENT.md`](./ADMIN_PRODUCTION_DEPLOYMENT.md)
- [`ADMIN_DASHBOARD_GUIDE.md`](./ADMIN_DASHBOARD_GUIDE.md)
- [`SANDBOX_TESTING_GUIDE.md`](./SANDBOX_TESTING_GUIDE.md)

## Unified application image

The same application image contains:

```text
FastAPI      :8001
Next.js      :3001
Celery worker
Celery beat
```

PostgreSQL and Redis are separate persistent services. The Compose application service is named `ithute-pay-bridge`, so administrators can deploy exactly with:

```bash
docker compose pull ithute-pay-bridge
docker compose up -d --force-recreate ithute-pay-bridge
```

## Environment separation

Never promote a test application credential into production. Create separate Pay Bridge `test` and `live` applications and separate API keys. The built-in administrator test lab owns a system-managed `test` application and forcibly uses the simulator.

## Administrator onboarding order

1. Confirm platform health and log in.
2. Create the merchant.
3. Create a test application.
4. Configure a sandbox/simulator provider.
5. Run the built-in full functional suite.
6. Create a test API key for the consumer.
7. Configure webhooks and complete consumer UAT.
8. Validate accounting and reconciliation.
9. Create a separate live application.
10. Configure approved production provider credentials.
11. Create a live API key and deliver it securely.
12. Perform controlled go-live validation.

## Non-negotiable production rules

- HTTPS before live credentials.
- Database and dashboard administrator credentials must be different.
- Provider secrets remain server-side and encrypted at rest where stored by Pay Bridge.
- Preserve PostgreSQL data volumes during normal deployment.
- Back up before migrations/releases.
- Use `Idempotency-Key` for financial creates.
- Consumers must verify webhook signatures and handle pending states.
