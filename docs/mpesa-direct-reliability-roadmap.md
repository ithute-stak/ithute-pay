# IthutePay direct M-PESA reliability plan

## Goal
Keep the existing direct Vodacom M-PESA Lesotho adapter as a first-class rail.
Golink remains an independent, optional provider adapter. Never replace the
direct M-PESA connection with Golink.

## Safety invariant
An outbound money-moving request can time out **after** Vodacom has executed
it. No automatic retry of collections, payouts, transfers, reversals, or
direct debits unless the same provider operation has been reconciled to a
definitive non-execution state and retries are explicitly safe.

## Implemented initial control
The admin live-verification route writes a durable started audit event before
attempting a money-changing provider operation. The event includes a local
run ID, operation, transaction reference and third-party conversation ID but
excludes customer MSISDN and credentials. Existing successful paths write
the executed event. An exception may leave a started-only attempt, which
must be investigated as **unknown**, not automatically marked failed.

## Required next steps (not yet implemented)
1. Create a database-backed `provider_operation` table, with scoped
   idempotency key uniqueness, provider, operation, tenant, amount, currency,
   reference, state, timestamps and protected identifiers.
2. Use an atomic state machine:
   `created -> dispatched -> processing -> succeeded|failed|unknown`.
   `unknown` is non-terminal until a verified provider query or authorised
   reconciliation resolves it.
3. Before outbound dispatch, persist the provider reference in the operation
   record in the same committed transaction that reserves the idempotency key.
4. For transport timeout, retain `unknown`, return a stable operation ID,
   never issue a new transfer automatically and never treat HTTP 200 as
   settlement evidence.
5. Add signed/validated callback ingestion where supported; deduplicate by
   provider event ID and transaction reference; defend against stale or
   conflicting state transitions; preserve raw redacted evidence.
6. Add reconciliation jobs, with rate limits and exponential backoff, using
   only read-only status queries and provider-approved settlement reports.
   Flag mismatches for manual review.
7. Add financial-ledger integration and balance/fee checks; use reversible
   ledger postings rather than deleting financial history.
8. Add fault-injection tests for 401, 409, 422, 500, read timeout, duplicate
   callback, delayed acceptance, and replayed payout requests; ship behind a
   feature flag and expand only after a successful staging rollout.
9. Protect privacy: no raw phone numbers, tokens, public/private keys,
   authorization headers or full provider payloads in routine logs.

## Language choices
- **Python + FastAPI**: existing APIs, provider contracts, orchestration.
- **PostgreSQL**: source of truth, idempotency uniqueness, audit and ledger.
- **Rust**: optional isolated high-assurance signing, parsing, or ledger math;
  adopt only after a clear benchmark or security case.
- **Go**: optional standalone webhook ingestion or reconciliation workers at
  high throughput, with a stable event schema and no extra payment source of
  truth.
- **Java or C#**: future enterprise banking adapters where partners require
  their ecosystems. Not needed to make current B2C reliable.
- **C++**: only for constrained native/device integrations; avoid running
  payment-business logic in C++ without a justified use case.

Do not introduce all languages into the same transaction path merely for
variety: more services create new deployment and consistency failure modes.
