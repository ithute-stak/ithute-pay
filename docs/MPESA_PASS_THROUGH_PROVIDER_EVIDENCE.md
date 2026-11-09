# Phase 7 — Pass-through authenticated-query evidence gate

The YYYY -> XXXX -> recipient pass-through workflow must NEVER accept a
merchant-supplied success status, unsigned callback, or a response missing
provider amount/party information as final evidence.

## This increment

- Defines a strict synthetic provider-query contract: reference, exact
  positive LSL amount, sending shortcode, beneficiary, provider transaction
  ID, final status and reversal flag.
- Rejects missing/wrong currency, amount, parties, reference, unrecognized
  status, missing successful provider transaction ID, and reversed transfers.
- Under an authenticated merchant/application scope, checks matching
  pre-existing operation intent, locks transaction, persists verified status,
  updates intent reconciliation state and calls the existing double-entry
  accounting adapter within the **same caller-managed database transaction**.
- Detects reuse of a provider transaction ID across known pass-through legs
  in the current database state. Further database-level uniqueness and
  concurrency tests are needed before production activation.
- Preserves the rule that no fee is earned until beneficiary payment succeeds;
  an unknown status must be queried, never re-submitted as a new payout.
- Adds no publicly callable reconciliation endpoint, no live B2B/B2C
  dispatcher, no SMS, and changes no direct M-Pesa/Golink integration.

## Important trust boundary

`ProviderQueryObservation` is a **structured input, not an authentication
token**. The trusted backend caller must independently authenticate a Vodacom
status-query response, verify the credential belongs to the intended account,
and supply *server-owned* expected source and beneficiary identifiers. Merely
constructing this Python object does NOT make an unsigned callback trustworthy.

The existing generic M-Pesa query response may not expose every mandatory
amount/party field, so this adapter MUST NOT be wired to that query without
confirmed provider capability. If the provider cannot supply these data in
an authenticated query, use a separately approved and audited reconciliation
feed before accepting a final outcome.

## Remaining for production readiness

- Certified Vodacom API/query contract and provider credential ownership.
- Signed/authenticated callback or independent statement evidence ingestion.
- Audited, persistent original provider evidence (not only its SHA-256 hash).
- PostgreSQL concurrency enforcement for provider ID uniqueness.
- Exception and reversal accounting, manual operator resolution.
- Inbound ledger policy, provider costs, SMS, and rollout monitoring.
- Central Bank of Lesotho and Vodacom authorization for temporary custodial
  XXXX pass-through movements, and a staging end-to-end dry run.

Live money movement is disabled and no production migration is applied by
this increment.
