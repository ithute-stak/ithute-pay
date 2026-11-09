# Phase 12 — audited pass-through exception investigation

This release adds a separate, operator-only case record for unresolved M-Pesa
pass-through operation intents and an append-only event log. The existing
reconciliation exception system is tied to ordinary reconciliation items and
must not be reused with a pass-through intent ID.

- One case per provider operation intent, database-enforced.
- Only active platform_admin/platform_super_admin users can invoke internal
  open/review functions. Caller must pass the *authenticated* operator identity.
- Cases are restricted to merchant and application scope.
- Open, investigating, escalated and closed states are independent of
  financial posting, provider settlement, refunds and account balances.
- Closing requires the underlying operation state to be closed and a
  non-sensitive evidence reference. This is **not** proof of settlement:
  provider evidence verification remains separate.
- Every changed state writes an exception event and an existing platform
  AuditLog entry in the same caller-controlled transaction.
- Customer-facing wording is generated only as an internal draft, always
  marked `safe_to_send=False`. It never claims a payment succeeded.
- Nothing in this phase dispatches M-Pesa or sends SMS/email/push notifications.

Migration `0018_mpesa_pt_exception_cases` creates two passive tables and
extends `0017_mpesa_pt_identity_receipts`. Review production migration
backup/rollback constraints before applying it; downgrade refuses to remove
populated audit records.

## Still required

- Access-controlled operator API/UI and tested explicit assignment workflow.
- Authenticated Vodacom query/statement verification and raw evidence retention.
- Safely idempotent notification outbox with opt-in recipients, delivery
  credentials and privacy controls; no delivery worker exists in this phase.
- Reversals, provider costs and inbound settlement accounting.
- Approved provider live-payment contract, regulated funds-handling review,
  sandbox recovery testing and production deployment sign-off.

Original direct M-Pesa and optional Golink integrations remain unchanged.
