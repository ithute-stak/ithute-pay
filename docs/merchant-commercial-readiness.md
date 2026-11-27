# IthutePay merchant commercial readiness — Phase 1

This phase implements **read-only, non-posting** financial-agreement previews,
without changing the existing payment providers, funds flow, or settlement ledger.

Existing functionality retained:
- Ithute master merchant registration
- Tenant enrollment and dual-control KYC approval
- Tenant-owned shortcode requests and verified provider evidence
- Dual-control agreement proposals and approval
- Tenant applications and inert read-only test credentials

## Administrative API

Requires a signed-in `platform_admin` or `platform_super_admin`.

`GET /api/v1/admin/merchant-network/tenants/{merchant_id}/readiness`
reports the status of tenant approval, KYC, own-shortcode custody, commercial
agreement, and a verified production M-PESA shortcode. Reports
`payment_execution_enabled: false` and `settlement_enabled: false`
**even when onboarding checks all pass**, because the actual money-moving
authorization gate has not been integrated yet.

`GET /api/v1/admin/merchant-network/agreements/{agreement_id}/quote?amount=100.00&direction=inbound`
calculates the agreed Ithute platform fee using Decimal and half-up cents,
with separate inbound/outbound fee rates. It excludes network/provider costs
and must never be used directly as a final settlement calculation.

The response includes both `net_after_platform_fee` and
`amount_plus_platform_fee` for comparison; actual contractual fee incidence
and merchant payable amounts require a signed settlement policy.

## Important restrictions

- No new database migrations.
- No payment collection, transfer, payout, provider balance or API key activation.
- No master-shortcode custody or mixed-merchant funds.
- No assumption that a verified shortcode automatically authorizes transactions.
- No automatic M-PESA or Golink enablement.
- A production money-moving gate must recheck ownership, KYC,
  provider account, agreement, active provider approval, idempotency and signed
  fee/settlement terms on **every** operation before this work may support live funds.

## Test

Run from the backend directory with the repository's usual test database and
environment fixtures:

`python -m pytest -q tests/test_commercial_pricing_quote.py tests/test_merchant_network_admin.py`

Do not deploy until CI and the isolated backend tests pass.
