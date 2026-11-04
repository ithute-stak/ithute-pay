# One-master bootstrap for Batlokoa / LoanHub

Verified LoanHub company: Batlokoa Financial Services, `4236a21f-5164-48aa-90f3-a35eccd23ae2`.

IthutePay database inventory on 2026-11-04: no merchants, no master merchant settings, no tenant contracts. Existing M-PESA environment settings are **not** an IthutePay merchant record.

## Before deployment

- Confirm the existing Vodacom master merchant shortcode belongs to the legal entity authorized to receive Batlokoa's payments. The database script **does not** prove that authorization.
- Confirm the sole LoanHub company remains Batlokoa and that IthutePay has no competing master merchant.
- Backup the IthutePay PostgreSQL database. Don't delete containers' database volumes.
- Deploy only after tests pass and the PR is reviewed.

## Read-only preview in the released IthutePay backend

```bash
python -m scripts.bootstrap_loanhub_master \
  --company-id 4236a21f-5164-48aa-90f3-a35eccd23ae2
```

Expected `action` is `create_master_merchant` for a new database or `register_existing_master` if one pre-existing merchant exists. A conflicting master or multiple merchants fails closed.

## Explicit, audited registration (after verification)

```bash
python -m scripts.bootstrap_loanhub_master --apply \
  --company-id 4236a21f-5164-48aa-90f3-a35eccd23ae2
```

This creates only one IthutePay merchant if none exists, and registers that merchant in `platform_merchant_settings`. When one merchant already exists, it reuses it without overwriting its name, ownership, credentials or metadata. A rerun is idempotent. A PostgreSQL transaction advisory lock serializes concurrent bootstraps.

The new account is named `IthutePay Master Merchant`; it is a **platform record**, not evidence of the legal account holder. The requested LoanHub mapping is stored only as `pending_authorization` metadata on a newly created record.

## Non-goals / still gated

- No API keys or LoanHub application issued; no live API binding is active.
- No tenant contract is created: master merchant may not enroll itself as tenant.
- No custody sharing, collections, payouts, settlements, workers, Golink, or provider flags are activated.
- IthutePay charges of zero are the requested policy only, not yet enforced in the fee engine. Provider charges may still apply.
- LoanHub's own-shortcode payment paths remain unchanged; switching those paths requires separate contract and tests.
- Direct M-PESA sandbox session authentication currently returns HTTP 400 from the VPS client and needs a separate fix.

Follow-up PR: implement explicit company/master authorization mapping, signed read-only API handshake, fee-engine zero-fee policy and routing tests with separate rollout flags.
