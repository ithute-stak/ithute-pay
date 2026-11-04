# Administrator-only Batlokoa fee-preview endpoint

This endpoint previews a zero-IthutePay-platform-fee policy without changing fees, settlements, or payment execution.

- `POST /api/v1/admin/merchant-network/loanhub-batlokoa/fee-preview`
- Requires authenticated `platform_super_admin` or `platform_admin` (same policy as the master merchant admin endpoints).
- Request: `{"amount":"150.00","currency":"LSL","operation":"collection"}`. `payout` is also supported.
- The server reads the existing master, production M-PESA configuration and dedicated inactive test application; the caller cannot supply merchant/company/application IDs.
- It fails closed if identity, application status, master custody flag or existing API-key count is inconsistent.
- Returns zero IthutePay fee **preview**, with `financial_posting_enabled:false` and `provider_charges_included:false`.

**Not yet connected to live fees:** no payments are created, no real fee is waived, and the existing `services/fees.py` and M-PESA direct integration are untouched.

Production use: deploy the PR #19 inactive app bootstrap and PR #20 admin verification first. Only test via an existing authenticated platform-admin session. Do not generate/print API keys, provider credentials, or customer data to test this endpoint.
