# Phase 9 — immutable party binding and unique provider receipts

This phase closes two gaps in the pass-through reconciliation foundation.

1. Before a transaction leg can be reconciled, its sender and beneficiary
   must be persisted as a one-time, server-approved identity binding to an
   existing reserved operation. The reconciliation service now compares
   both parties to that binding, *not* to caller-provided identity alone.
   An attempt to change the binding fails.
2. Each successfully reconciled M-Pesa transaction ID is stored against its
   specific operation with a database-enforced unique provider/transaction ID.
   This prevents two separate transactions or legs from claiming the same
   provider evidence, including concurrent insert races. The evidence hash is
   recorded, and replay of an identical confirmed result is idempotent.

Alembic revision `0017_mpesa_pt_identity_receipts` creates both tables.
Existing direct M-Pesa and Golink integration code is unchanged.
Nothing here sends or receives money; the existing live pass-through
execution path remains disabled.

## Critical boundary

`bind_leg_identity` is an **internal** function, not an authorization
mechanism by itself. A future adapter must resolve `source_party` and
`destination_party` from approved tenant shortcode credentials and a
persisted, authenticated beneficiary before calling it. Never populate the
binding directly from client-submitted shortcodes or provider responses.

All result and accounting mutations must be committed in a single database
transaction. Any uniqueness error must roll back; never treat it as success.

## Release gates still open

- Verify real Vodacom account, query and beneficiary evidence contracts
  using provider-authorized sandbox credentials.
- Enforce provider authorization, credential/account ownership and KYC,
  separately from internal binding.
- Persist securely authenticated raw statement/query evidence under
  retention and privacy controls; only its digest is stored here.
- Test recovery under concurrent PostgreSQL sessions and worker crashes.
- Complete incoming reconciliation, non-zero provider costs and reversals.
- Implement certified dispatcher with reconciliation-first retries, an
  outbox worker, SMS delivery and operations monitoring.
- Obtain regulatory and Vodacom approvals and deploy reviewed migrations
  before considering production enablement.
