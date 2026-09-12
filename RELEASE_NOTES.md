# Ithute Pay Bridge — release notes

## 2026-07-26 — administrator docs, consumer docs, test lab and responsive UI upgrade

### Administrator documentation

Added dedicated documentation for:

- sandbox/UAT deployment;
- GHCR/VPS production deployment;
- Nginx/TLS routing;
- administrator dashboard operations;
- production release/go-live checks.

The same deployment guidance is summarized inside **Dashboard → Documentation**.

### Consumer integration documentation

Added a detailed consumer handbook covering:

- test/live application credentials;
- Bearer authentication;
- financial idempotency;
- optional HMAC request signing;
- collections, payouts, B2B transfers, authorizations, mandates, checkout, payment links and reversals;
- accounting/settlement APIs;
- asynchronous resource states;
- webhook HMAC verification;
- Python and server-side TypeScript examples;
- sandbox and go-live checklists.

### Built-in sandbox functional test lab

Added administrator endpoints:

```text
GET  /api/v1/admin/testing/catalog
POST /api/v1/admin/testing/run
POST /api/v1/admin/testing/run-all
GET  /api/v1/admin/testing/history
```

The lab creates/reuses an isolated system-managed `test` merchant/application and forces its provider configuration to M-Pesa simulator mode.

Twelve modules cover:

1. collections;
2. payouts;
3. B2B transfers;
4. two-stage authorization/commit;
5. direct-debit mandate/charge;
6. hosted checkout;
7. payment links;
8. reversals;
9. settlement requests;
10. double-entry accounting integrity;
11. reconciliation matching;
12. webhook HMAC generation/independent verification.

Test executions are written to the audit log. RTK Query invalidation refreshes operational dashboard data after tests.

### Frontend and Redux

- Added Redux UI state for desktop sidebar collapse/expand.
- Sidebar preference persists in browser local storage.
- Mobile navigation remains a full drawer.
- Added Redux sandbox-test configuration/recent-result state.
- Added Redux-controlled documentation tabs.
- Added RTK Query endpoints for sandbox catalog, history and test execution.
- Added **Sandbox test lab** and **Documentation** navigation entries.
- Updated shared cards, inputs, buttons, page headers, data tables and stat cards to use theme tokens.

### Global stylesheet

The user-supplied `globals.css` is now the frontend global stylesheet. Pay Bridge aliases (`paybridge-page`, `paybridge-hero`, `paybridge-panel`, `paybridge-stat`, `paybridge-soft`) are appended so new gateway UI can use the supplied theme without adopting LoanHub-specific component naming.

### Deployment

The unified application service is now consistently named:

```text
ithute-pay-bridge
```

So normal VPS application deployment can be:

```bash
docker compose pull ithute-pay-bridge
docker compose up -d --force-recreate ithute-pay-bridge
```

FastAPI remains on `8001` and Next.js on `3001` inside the unified image; PostgreSQL and Redis remain persistent supporting services.

### Additional fix

Hosted checkout/payment-link expiry comparison was made robust for both timezone-aware and timezone-naive datetimes, which is important for SQLite test execution while preserving PostgreSQL behavior.

### Validation

- backend tests: **16 passed**;
- clean Alembic migration: **0002_accounting_auth (head)**;
- API/WebSocket/docs route inventory: **101 operations**;
- TypeScript/TSX syntax parse: **47 files, 0 syntax diagnostics**;
- Compose/workflow YAML parsing: passed;
- host Nginx syntax: passed.

A complete `pnpm install/typecheck/build` and Docker image build were not possible in the artifact environment; see `VALIDATION_REPORT.md`.

## Gateway middleman upgrade — 2026-07-26

- Added platform-owned, database-backed M-Pesa sandbox/production configuration with authenticated environment activation.
- Added provider callback, result, queue-timeout and browser-return endpoints plus callback audit/idempotency logging.
- Added sector-neutral client routing (`merchant_number`, routing keys and `customer_reference`) for schools, micro-lenders, insurers and other platforms.
- Added M-Pesa settlement destinations per client and automated gross -> fee -> net settlement instructions using B2B or B2C.
- Added fee packages with fixed, percentage, minimum and maximum commercial rules and merchant assignments.
- Added signed client webhook configuration to the platform administration UI.
- Added a public routed collection endpoint with optional idempotency keys and normalized client reference/reason metadata.
- Added settlement worker/reconciliation behavior and real-time gateway events after database commit.
- Corrected Direct Debit Payment so amount and currency are sent to M-Pesa.
- Added Providers, Client routing, Fees & packages, Settlements and payment return frontend pages.
- Added regression coverage for routed collections, fee deductions, idempotent retries, settlement ledger clearing and provider callback audit behavior.

## Public visitor documentation update

- Added a public `/documentation` route that requires no platform login.
- Added a **Visitor documentation** button to the sign-in card.
- Added public integration examples for routed collections, merchant endpoints, payment lifecycle states, M-Pesa provider callbacks/results/timeouts, signed client webhooks, direct debit states, settlements, HTTP errors, and common provider result codes.
- Added a visitor-documentation shortcut inside the authenticated Documentation Center.
- Public documentation deliberately excludes provider credentials, admin configuration secrets, platform operations, and production keys.
