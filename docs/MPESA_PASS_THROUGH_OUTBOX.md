# M-Pesa Phase 5 — durable operation intent (non-executing)

This milestone creates an auditable operation-intent record for each B2B
funding, B2C beneficiary payout, or permitted refund. The reservation is made
in the same SQLAlchemy transaction as the corresponding pass-through leg
transition. No API endpoint, wallet credential, or provider network call is
added here.

## Critical safety behavior

- Exactly one operation intent per pass-through transaction leg, enforced
  by `uq_mpesa_pt_intent_leg`.
- An immutable provider correlation reference is reserved before any future
  transport can be considered. Duplicate reference use across transactions
  is prohibited by `uq_mpesa_pt_intent_reference`.
- A repeated attempt with the same reference returns the original intent;
  a different reference is rejected. A reserved or uncertain operation is
  **never** automatically sent again by this code.
- Beneficiary payout requires independently confirmed funding.
- Refund reservation is blocked while beneficiary status is uncertain.
- The intent table has **no dispatch worker** or live transfer API.
- Existing direct M-Pesa, Golink and other payment integrations remain
  unchanged, and platform fees remain tenant-agreement configurable.

## Still required for real transfers

1. A certified Vodacom B2B/B2C contract and explicit intermediary
   permissions for each shortcode, with regulatory classification confirmed.
2. Reconciliation-first recovery for reserved/unknown operations, with
   independently authenticated provider results and amounts.
3. Actual dispatcher with restart-safe claims, reconciliation-only recovery,
   strict credentials/tenant ownership, rate limits, and a disabled-by-default
   activation gate. Outbox storage alone is **not exactly-once delivery**.
4. Posted, balanced settlement-liability accounting through the existing
   financial ledger before any live transfer.
5. Callback authentication, SMS outbox, audit logs and end-to-end sandbox
   tests including provider timeout/failure/reversal.
6. Production Alembic upgrade to revision
   `0016_mpesa_pt_operation_intents` after backup and staging rehearsal.

This is the next safety foundation, **not the complete production executor**.
