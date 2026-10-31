# Golink optional adapter — Phase 1 architecture audit (2026-10-28)

## Scope and source of findings
Reviewed repository README, docs/CENTRAL_PAYMENT_PLATFORM.md, docs/GATEWAY_MIDDLEMAN_ARCHITECTURE.md, and docs/SECURITY.md on the default branch. This is a documentation-level architecture audit; it is **not** an exhaustive code inspection, passing test run, or approval to transact live funds.

## Existing capabilities to preserve
- Central Merchant -> Application -> ApiKey contract; app-scoped ipb_test_/ipb_live_ credentials.
- Direct M-Pesa integration, including C2B, B2C, B2B, mandate/direct debit, query, reversal, and existing callbacks.
- Existing EcoCash and PayPal provider integrations, simulator/sandbox modes.
- Ledger, fees, merchant payable balances, settlement instructions, reconciliations, idempotency, audit and signed merchant webhooks.
- Central Auth/Push, consumer API/SDK contracts, and LoanHub isolation from provider secrets.
- Existing payment routing; avoid changing defaults or provider selection for current merchants.

## Adapter contract
Implement Golink as a **separate optional provider** with immutable internal payment IDs and external Golink payment ID recorded separately. Never rename or replace the existing mpesa provider with Golink. Route choice should be per merchant/application/rail/environment as supported by existing infrastructure, and should default to current behavior until explicitly enabled.

Use provider transaction identifiers as external correlation keys, **not** internal ledger primary keys. Preserve merchant/application/environment boundaries and authoritative internal accounting. Map Golink PENDING/PROCESSING/SUCCEEDED/FAILED/CANCELLED onto existing platform lifecycle without treating PROCESSING as success. Handle payment.refunded only within supported rail/refund semantics.

## Safety invariants
1. No destructive migration; no deletion or rewrite of existing credentials, transaction history or direct M-Pesa integration.
2. No automatic alternate-provider retry for a transaction with unknown/PROCESSING outcome; reconcile with the original provider and idempotency key.
3. On timeout, reuse Golink's original idempotencyKey and payload; conflicting intents must fail closed.
4. Verify X-Golink-Signature HMAC SHA-256 over raw request bytes using timing-safe comparison. Ensure durable event ingestion, dedupe and at-least-once processing safety before acknowledging 2xx.
5. Perform authenticated provider-side payment detail verification and reconcile merchant, amount, currency, environment, rail and internal payment reference prior to posting ledger entries.
6. Reversals/refunds are separate compensating movements; do not rewrite prior successful ledger rows.
7. Sandbox glk_test_ and production glk_live_ credentials are segregated and secret; provider disabled by default.
8. Merchant API/webhook contracts remain unchanged so LoanHub, Khanya POS and external integrations never depend on Golink's schema.
9. Golink downtime, revocation or removal must not prevent existing direct-provider payment processing.

## Implementation phases / checkpoints
1. [in progress] Source-level inspection of provider registry, config models, routing, payment services, callbacks, workers, tests, and migrations; record exact paths.
2. Add Golink adapter with sandbox HTTP client, typed payload translation, credentials/feature flag.
3. Collections (MPESA/ECOCASH) with persisted idempotency.
4. Signed webhooks, durable inbox, statuses and reconciliation.
5. Other permitted rails / payouts with rail-specific restrictions.
6. Mandates and recurring payments.
7. Explicit, safe routing configuration with no unknown-outcome failover.
8. Merchant-facing config/monitoring/reporting.
9. Regression and sandbox certification: direct M-Pesa retained, invalid signatures, duplicates, delayed success, timeout, 409, cross-tenant, refunds/settlements, worker recovery.
10. Operational release and rollback (separate signoff).

## External prerequisites
Actual sandbox API key, approved test accounts/phone numbers, active PSP rail configurations, webhook registration secret and accessible HTTPS callback endpoint. These are not needed to code the adapter, but **are required** for end-to-end sandbox certification. Regulatory, commercial and settlement confirmation required before live rollout.

## Next action
Inspect source-level implementation paths and tests before editing production code. The documentation references FastAPI in apps/backend/, Next.js in apps/frontend/, and Celery workers, but no source paths have yet been independently established by this audit.
