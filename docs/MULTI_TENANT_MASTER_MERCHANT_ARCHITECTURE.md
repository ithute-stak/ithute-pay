# IthutePay Master Merchant and Tenant Merchant Architecture
Status: design proposal — not enabled in production
Date: 2026-11-03

## Purpose
Operate IthutePay as a multi-tenant payment orchestration platform. Ithute owns
the master platform, provider connections, routing and contractual fees; each
tenant owns its application credentials, customers, transactions, commercial
agreement and reporting scope. Direct Vodacom Lesotho M-PESA is retained as an
independent core rail; Golink remains optional.

## Two approved operating modes
1. `own_shortcode`: tenant has an approved provider shortcode. Ithute applies
   centrally governed provider API credentials and platform policies; routing
   substitutes ONLY the verified, tenant-owned service provider code in
   provider requests, subject to Vodacom approval/technical capability. Funds
   settle directly into the tenant's provider merchant balance. Ithute records
   transactions and its fee receivable; cannot present its internal ledger as
   a custodial balance at Vodacom.
2. `master_shortcode`: onboarding-approved tenant lacks its own provider
   merchant. Ithute's master shortcode accepts funds under an explicitly
   authorised payment-facilitator/aggregation arrangement. Every movement must
   be posted to a distinct tenant liability and reconciled with actual
   master/provider funds. Tenants do not inherit master provider secrets.
   Suspended until acquiring-provider and applicable regulatory authorisation,
   KYC/AML, safeguarding and settlement terms are documented.

## Existing assets to reuse
- `merchants`, `applications`, `api_keys` and merchant-context auth.
- `gateway_provider_configurations` platform-owned provider secrets.
- `merchant_gateway_profiles`, `merchant_routing_keys`,
  `merchant_settlement_accounts`.
- `fee_packages`, `fee_package_rules`, `merchant_fee_packages` and
  existing `FeeRule` compatibility.
- `provider_transactions`, `provider_operations`, `settlement_instructions`,
  `merchant_funding_accounts`, `journal_entries` and `journal_lines`.
- Direct M-PESA tenant shortcode provider factory and `tenant_routing.py`.
- Existing collection/unfunded payout claims and CI; pending transfer/settlement/
  reversal/funded payout safety work must be completed prior to enabling shared custody.

## Proposed additive data model
- `platform_merchant_settings`: immutable master `merchant_id`, status,
  provider permissions, financial control configuration.
- `tenant_merchant_contracts`: `tenant_merchant_id`, `master_merchant_id`,
  custody mode, status, KYC status, approved limits, start/end and version.
- `tenant_provider_accounts`: merchant_id, provider, environment, shortcode
  encrypted where appropriate, ownership verification state/evidence reference,
  effective dates, default flag, unique active provider shortcode assignment.
- `merchant_commercial_agreements`: merchant_id, fee schedule version,
  in/out/transfer/refund pricing, provider-cost responsibility,
  platform-charge responsibility, payer, caps, effective dates and approval.
- `transaction_fee_assessments`: immutable per-transaction amount, currency,
  merchant, provider fee, Ithute service fee, payer, version, reason and tax
  metadata; reverse using compensating entries.
- `tenant_fund_balances` or preferably derived ledger accounts for:
  master-held tenant payable, available, reserved, unsettled, disputed,
  and fee payable; never a manually editable balance.
- `provider_balance_snapshots`, `tenant_settlement_batches`,
  `settlement_approvals`, and `reconciliation_exceptions`.
- Add `merchant_id` to all new scoped objects; enforce through API queries,
  ownership checks, uniqueness constraints and database isolation tests.

## Provider-routing contract
1. Authenticate application API key; resolve tenant from application, NEVER
   from user-supplied `merchant_id`.
2. Resolve approved tenant contract and enabled environment; reject suspended,
   unverified or out-of-limit tenant.
3. Load centrally owned provider connection and permitted capabilities.
4. `own_shortcode`: select verified and approved shortcode from the tenant
   provider account record; never trust `business_shortcode` supplied in
   untrusted payment metadata or a POS client.
5. `master_shortcode`: require approved aggregator/custody contract; use
   platform shortcode, bind the intended tenant in internal ledger and
   correlation references; deny withdrawals above settled available funds.
6. Reserve a tenant-scoped idempotent operation, commit before network call,
   then dispatch exactly once. Unknown outcomes block redispatch until
   authoritative reconciliation.
7. Validate and deduplicate callbacks, reconcile external references, post
   tenant-specific double-entry journal lines, and emit tenant-scoped events.

## Fee allocation — separate provider cost from Ithute revenue
Define three independent concepts:
- Provider/rail charge: the cost Vodacom or another provider charges.
- Ithute commercial fee: the agreed in/out service price paid by tenant.
- Customer charge: optional, only when explicitly allowed and disclosed.

Example (illustrative, NOT contractual rates):
A customer pays LSL 100, external provider charge LSL 1 and the Ithute
inbound merchant fee LSL 2. If business is contractually responsible for both
charges, merchant entitlement is LSL 97 in master-held mode; Ithute revenue is
LSL 2, provider expense/pass-through is LSL 1. For provider-direct mode,
LSL 100 is paid at provider to tenant according to provider arrangements and
Ithute accrues LSL 2 fee receivable, to be collected via approved funding
arrangement or invoice; do NOT pretend Ithute can silently deduct it from
funds held in the tenant's own provider merchant account.

A master-merchant may pay provider charges centrally but must allocate them
per agreement and record who ultimately bears the cost. If Ithute subsidizes
provider fees, record its expense rather than deducting tenant funds.
For outbound operations require full funds reservation for principal plus
tenant-borne costs prior to dispatch.

## Merchant portal
- Business onboarding and review; ownership/KYC status.
- Shortcode submission and verification, with activation requiring provider
  evidence and master/platform approval. No direct merchant edits to master
  secrets, provider base URLs, callback signing or global routing.
- Own-versus-master processing account application and status.
- Applications (POS, website, LoanHub), sandbox/live API keys, SDKs,
  sample integrations, signed webhooks, event logs, rate limits.
- Fee agreement viewer with current and historical in/out rates.
- Real-time transaction list, payout controls, provider reconciliation,
  fee invoices, subledger settlement, disputes/refunds and exports.
- Multi-user tenant roles and audit log; platform support access audited.

## Master portal
Merchant lifecycle approvals, verified shortcode ownership, provider
configuration/health, commercial contracts with four-eyes approval, fees
and revenue, provider costs, settlement batches, reserves, reconciliations,
risk limits, per-tenant financial exposure, audit and support operations.

## Merchant integration API (proposed, versioned)
- `POST /api/v1/merchant/shortcodes` submit ownership proof, never activate itself
- `GET /api/v1/merchant/shortcodes` list only own accounts
- `GET /api/v1/merchant/agreements/current` read approved rates
- `POST /api/v1/payment-intents`, `POST /api/v1/payouts`,
  `POST /api/v1/transfers` reuse existing APIs with server-resolved tenant
- `GET /api/v1/merchant/balances` label source: provider-reported vs
  master-held available/reserved/settled, and snapshot timestamp
- `GET /api/v1/merchant/fee-statements`
- `POST /api/v1/merchant/settlement-requests` only where custody is permitted
- `POST /api/v1/webhooks` and `GET /api/v1/webhooks/events` reuse existing
  webhook contract where available; do not duplicate existing endpoints.

## Non-negotiable controls
- Prevent cross-tenant API access and shortcode spoofing.
- Provider secrets stored only in the platform encryption boundary.
- Distinguish merchant-specific gross receipt from Ithute service revenue.
- Never dispatch a second request on uncertain provider outcome.
- Reconcile the master provider account total against the sum of tenant
  liabilities, reserves, fee payable, pending settlement and discrepancies.
- No commingling tenant liabilities with Ithute operating revenue.
- Maker/checker approvals for new master-shortcode tenants and rate changes.
- No production activation until Vodacom approval and Lesotho regulatory,
  safeguarding, AML/KYC and consumer disclosure review are complete.

## Delivery sequence
1. Tenant/master identities, authorisation and shortcode ownership verification.
2. Commercial agreement/versioned fee schedule and fee assessment.
3. Provider-direct POS integration with verified shortcode and provider-reported
   balances; tests proving tenant isolation.
4. Master-held ledger/custody mode behind a disabled feature flag.
5. Settlement, reserve, reconciliation, dispute, payout safety and accounting.
6. APIs/SDK updates, portals and contract tests.
7. Independent review and regulatory/provider approvals before shared-custody
   release; stage, certify, then gradual production rollout.

Do not replace existing M-PESA or Golink integrations, mutate existing
production balances, or deploy money-moving routes from this design alone.
