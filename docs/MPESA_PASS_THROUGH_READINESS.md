# Phase 10 — Approved account preflight and reconciliation-only recovery

This non-posting module validates the necessary merchant/account metadata
before a certified future provider dispatcher could be considered.

For tenant YYYY and platform XXXX, the internal preflight fails closed
unless there is exactly one active master; an active tenant and platform;
an approved, KYC-verified, effective own-shortcode contract; exactly one
effective LSL pricing agreement; one enabled verified M-Pesa account for
each merchant/environment; and two distinct shortcodes.

The readiness object **always** returns
`live_execution_authorized=False`. A dedicated guard raises
`PermissionError` for any attempted live dispatch. The presence of verified
local account records is NOT a substitute for Vodacom's written B2B/B2C
permissions or payment intermediary authorization.

Crash recovery for existing funding/payout/refund operation intents:
- A final/closed leg needs no automatic retry.
- A reserved leg with no bound sender/beneficiary needs manual review.
- A reserved or uncertain leg with a bound sender/beneficiary requires
  **read-only lookup of its original operation reference**. This cannot
  create or re-submit a payment.
- A different tenant/application cannot inspect the transaction.

Existing direct M-Pesa and Golink integrations are untouched.

Remaining release gates: approved real Vodacom account and transaction
query contract; provider-authenticated raw evidence; licensed/authorized
temporary custody; certified dispatcher; safe retry semantics; incoming
accounting, provider costs, refunds/reversals and SMS; PostgreSQL concurrency
testing; and production migration/deployment approval.
