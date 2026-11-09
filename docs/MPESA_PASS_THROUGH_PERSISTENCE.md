# M-Pesa pass-through persistence (Phase 3, non-executing)

This increment adds an additive SQLAlchemy model and merchant-scoped store for
the YYYY -> XXXX -> client pass-through design. It preserves the already
merged configurable quote calculator and pure lifecycle transition rules.

## Guarantees in this increment

- Quote snapshot keeps the approved agreement version and decimal amounts.
- Per-application idempotency key has a database uniqueness constraint.
- A conflicting replay is rejected rather than repriced.
- A merchant/application must match before a transaction can be read or changed.
- Funding, onward payment, and refund each have independent statuses and
  verified-evidence hashes, stable correlation references and provider IDs.
- An uncertain payment cannot be silently re-dispatched with a new reference.
- Platform fee is a lifecycle *calculation*, not a posted ledger credit.
- No API endpoint or M-Pesa provider is connected to this store.

## Release gates — NOT satisfied by this change

1. Locate and validate the current production Alembic migration head; add the
   forward-only migration against that exact head before deployment. Do not
   use automatic create_all against production.
2. Implement an atomic provider-operation outbox and transaction reservations
   on PostgreSQL; locking in this store alone does not make provider calls
   exactly-once across failures or workers.
3. Implement double-entry tenant settlement liabilities and genuine fee
   recognition in the existing financial ledger. Never infer real cash
   availability from these calculated quote amounts.
4. Authenticate provider callbacks/queries independently; reconcile provider
   transaction IDs, amounts, merchant accounts, currency and balances.
5. Integrate approved B2B/B2C routing, recovery, refunds and SMS delivery.
6. Obtain Vodacom authorization and applicable regulatory clearance before
   enabling live pass-through execution.

The current model is deliberately not registered as a public write API.
The new table will be created by the existing test fixtures with Base.metadata,
but production deployment must wait for the properly chained Alembic migration.

Run in the backend:
`python -m pytest -q tests/test_mpesa_pass_through_store.py`
