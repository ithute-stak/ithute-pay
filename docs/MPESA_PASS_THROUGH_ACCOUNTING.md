# Phase 6 — double-entry posting for verified pass-through outgoing flows

This module adds an *internal* accounting adapter over the existing
`JournalEntry`, `JournalLine`, `LedgerAccount` and compatibility
`LedgerEntry` models. It does not create a new ledger, initiate an M-Pesa
transfer, register an API route, or enable an outbox consumer.

Only the following accounting contract is presently supported:

- **Outgoing LSL**, from the tenant's own merchant to IthutePay XXXX.
- **No provider costs** on either movement and fee payer = tenant.
- Tenant fee comes from the immutable, approved, tenant-specific quote snapshot.
- Provider evidence for each leg has already been verified independently
  and persisted to the pass-through transaction store.
- Each leg has a corresponding, same-tenant, reserved outbox operation intent.

## Journal for example M1,000 disbursement and M10 fee

| Confirmed event | Debit | Credit | Amount |
|---|---|---|---|
| Funding YYYY -> XXXX | Provider clearing | Merchant payable | M1,010 |
| B2C XXXX -> client | Merchant payable | Provider clearing | M1,000 |
| Earned fee (after B2C success) | Merchant payable | Gateway fee revenue | M10 |

On refund, instead of paying the client, the approved return of the full
M1,010 is recorded as debit merchant payable / credit provider clearing.
Unconfirmed movements never become journal postings. The fee is not recognized
on timeout, failure, refund, or unknown beneficiary status.

## Operational rules

- Call `post_verified_outgoing` **only from an internal evidence-verified
  service**, never from client-provided success flags or a public endpoint.
- Commit the verified provider result and all associated journal entries in
  the **same SQLAlchemy database transaction**. Roll back all on failure.
- The journal entry's existing unique source-reference constraint plus strict
  line comparison protects against duplicate posting and divergent replays.
- The repository's `post_journal` controls balanced debits/credits; every
  resulting line must be reconciled to actual provider evidence.
- The existing M-Pesa and Golink provider paths are unchanged.

## Not implemented / release blockers

- Incoming collection and B2B settlement ledger policies.
- Non-zero M-Pesa provider-cost allocation or provider fee reversals.
- Independently authenticated provider callbacks/status queries.
- Dispatch workers, ledger reconciliation against Vodacom statements, SMS.
- Production deployment and certified live money movement.

The provider clearing journal is an *accounting claim*, not proof that XXXX
has sufficient available float. Final financial sign-off and Lesotho payment
provider/regulatory authorization are separate requirements.
