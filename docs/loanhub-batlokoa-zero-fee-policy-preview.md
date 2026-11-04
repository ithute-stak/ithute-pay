# Batlokoa zero-platform-fee preview (non-posting)

This is a **pure calculation policy** for the verified LoanHub Batlokoa company and IthutePay master merchant, not an activated fee exemption or production payment route.

- Verified company: `4236a21f-5164-48aa-90f3-a35eccd23ae2`
- Verified master merchant: `3cc13734-5cd3-4ab4-9e4b-d378b715fa3f`
- Existing provider shortcode: `38542`
- Dedicated application: `LoanHub - Batlokoa Financial Services` (inactive, test-only)
- Zero IthutePay platform fee preview for collection or payout in LSL: M0.00 and 0%.
- Provider/network fees, withholding, and settlement costs **are not** included in the zero-platform-fee policy.

The policy refuses other merchant/company IDs, active applications, unexpected currencies and invalid amounts.

**Not connected to `services/fees.py` or payment processing yet.** Activating a platform-fee exemption requires an explicit agreement, server-verified company-to-application authorization, provider custody approval as applicable, accounting/settlement integration, and PostgreSQL reconciliation tests. Do not assume quoting this policy modifies the financial ledger.
