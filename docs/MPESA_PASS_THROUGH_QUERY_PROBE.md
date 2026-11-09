# Phase 8 — M-Pesa provider status query capability probe

The existing direct M-Pesa client already supports
`queryTransactionStatus/` via `MpesaClient.query`, but a generic successful
response does not necessarily include exact funding amount, original source
shortcode, beneficiary identity and final status. **Never infer those from an
earlier request** to make a provider query look complete.

This safe increment adds
`services.mpesa_pass_through_query_probe.probe_sandbox_query`:
- Performs a read-only status query through an explicitly sandbox-configured
  M-Pesa client with country LES, currency LSL and market vodacomLES.
- Requires its configured shortcode to match the server-owned source account.
- Inspects the raw provider result. Only complete raw amount, currency,
  sender, receiver, transaction reference, final status and transaction ID
  can qualify as sufficient evidence.
- Rejects mismatched, reversed, incomplete or ambiguous responses rather
  than synthesizing success from a successful HTTP/INS response code.
- Does not update the database, call `reconcile_authenticated_query`, post
  accounting, submit B2B/B2C, refund or send SMS.
- Leaves the direct M-Pesa and Golink integrations untouched.

The raw field names in the probe are **candidate fields** that must be
confirmed with Vodacom Lesotho. The current code does not assert Vodacom
returns all those fields or certify live operations.

## Required next work

1. Run a provider-approved sandbox query from the correct credential account
   and inspect the documented returned fields, keeping credentials/redacted
   customer identifiers out of logs.
2. If the response lacks mandatory fields, obtain a signed/independently
   authenticated settlement feed or provider-certified evidence API; do not
   relax validation or accept merchant-provided identity.
3. Persist expected source/destination and approved operation identity before
   funding/payout. A caller-supplied `ExpectedMovement` alone is not an
   immutable trusted source of identities.
4. Add a provider transaction ID uniqueness constraint across every leg,
   durable raw evidence audit, and concurrency/rollback tests in PostgreSQL.
5. Connect a trusted reconciliation worker only after provider contract,
   KYC/shortcode permissions, regulatory and operational approvals. Keep
   the execution feature flag disabled by default.
6. Test live-candidate execution exclusively in an approved sandbox with
   deterministic timeout, duplicate, reversal and restart scenarios.

No production deployment or money movement is authorized by this phase.
