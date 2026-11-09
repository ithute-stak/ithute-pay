# Phase 4 — Passive pass-through Alembic migration

Migration: `0015_mpesa_pass_through_state`
Parent: `0014_tenant_push_manual_retries`

This forward-only deployment increment adds the table
`mpesa_pass_through_transactions` with frozen column definitions,
idempotency uniqueness, tenant/application FKs, amount checks, and
per-leg status validation. It does **not** enable funds movement, invoice
creation, custody, provider operations or fee posting.

## Deployment constraints

- Back up production PostgreSQL and confirm the exact existing Alembic
  revision is `0014_tenant_push_manual_retries` before applying `0015`.
- Review locking and DDL timing on the production database. Migration does
  not modify existing merchant funds or existing payment transaction tables.
- Never run `Base.metadata.create_all` against production.
- Do not downgrade or drop a table containing business audit records in live
  production. The downgrade exists for disposable test environments only.
- Verify table, constraints, indexes, and database privileges after upgrade.
- Keep all real B2B/B2C provider routes disabled pending provider permissions
  and the approved settlement ledger and outbox integration.
- The targeted test runs a temporary SQLite DDL simulation, not a real
  PostgreSQL migration rehearsal. A disposable PostgreSQL rehearsal remains
  a release gate.

The original M-Pesa and Golink integrations remain untouched.
