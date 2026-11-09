# M-Pesa Pass-Through — Lifecycle Integration Gate (Phase 2)

The feature is intentionally **non-posting and not provider-connected**.
Do not interpret a pure state transition as evidence that an M-Pesa transfer
occurred. `mpesa_pass_through_lifecycle` accepts provider evidence only from
an independently authenticated, tenant-checked, amount-checked integration.

## Intended flow

1. Create an approved tenant-specific immutable quote (from an approved
   agreement and verified tenant context, never a request-supplied tenant ID).
2. Persist the exact funding reference and the initial `processing` state
   before any network dispatch.
3. Obtain confirmed B2B funding YYYY -> XXXX. Record provider evidence and
   a tenant settlement liability; do not recognize fee revenue yet.
4. Only after funding success, initiate B2C XXXX -> client using one stable
   operation identity. Unknown statuses must be reconciled by lookup, never
   resent with a fresh reference.
5. After independently verified B2C success, release the liability and book
   platform revenue, subject to actual provider costs and tax treatment.
6. Failed beneficiary payout: investigate, then process an authorized refund
   to YYYY if appropriate; keep the liability until the refund succeeds.
7. SMS and dashboards must show each actual leg status. A quote is not a
   receipt, and an unknown payout is not a failed payout.

## Production adapter still required

- Real PostgreSQL models, unique indexes, Alembic migration, transactional
  outbox and row-level locking for cross-worker concurrency.
- Provider operation pairing, credential ownership checks, signed callbacks
  or authenticated status queries and correlation of amounts/currency.
- Precisely reconciled tenant liability journal with balanced entries and
  unknown/failed/refund workflows.
- Real SMS delivery and reconciliation reporting.
- Vodacom authorization and applicable regulatory clearance.
- An explicit production feature flag that defaults to disabled.

This PR adds **no new API for fund transfers**, no DB table, and no live
M-Pesa call. Existing direct M-Pesa and Golink adapters are unchanged.

Test: `cd apps/backend && python -m pytest -q tests/test_mpesa_pass_through_lifecycle.py`.
