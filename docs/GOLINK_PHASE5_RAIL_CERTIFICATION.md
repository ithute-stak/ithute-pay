# Golink Phase 5 — additional rail certification gates

**Status: NOT CERTIFIED. No payment execution permitted.**

This checklist is evidence-driven. No flag, merchant configuration, or
administrative override is sufficient to activate CARD, CPAY, EFT or PAYSLIP.
The draft executor in `providers/golink/additional_rails.py` must remain
non-executable until new, reviewed provider-specific execution code is built.

## Common requirements (each rail separately)

- [ ] Provider-published sandbox API schema and authorization verified against real requests
- [ ] Exact rail name and supported direction, currency, and amount limits confirmed
- [ ] Payer/payee identifiers and mandatory fields documented using redacted examples
- [ ] Unique idempotency/replay behavior verified, including timeouts and ambiguous outcomes
- [ ] Provider payment ID and merchant attempt IDs correlated across retries
- [ ] Signed webhook format, replay protection and delivery/retry behavior verified
- [ ] Read-back reconciliation via authenticated GET verified for every terminal outcome
- [ ] Duplicate, stale, out-of-order and conflicting callbacks proven ledger-safe
- [ ] Cancellation/refund/reversal semantics and permissions tested or explicitly unsupported
- [ ] Audit logs and secrets redaction verified without persisting credentials or payment secrets
- [ ] Accounting invariants, multi-tenant isolation and reconciliation tested with PostgreSQL
- [ ] Rollback / kill-switch test proves direct M-PESA and EcoCash routes remain unaffected
- [ ] CI tests pass on a branch reviewed by two authorized maintainers
- [ ] Non-production sandbox acceptance signed off before any separate live release approval

## CARD

- [ ] Provider confirms hosted checkout/tokenization, token lifetimes and PCI scope
- [ ] No PAN, CVV, expiry, track data or PIN enters IthutePay application/logs
- [ ] Redirect / return URL and asynchronous confirmation are reconciled
- [ ] 3-D Secure / SCA, authorization, capture, settlement and chargeback behavior confirmed
- [ ] Card refunds and partial captures handled only if provider supports them

## CPAY

- [ ] Confirm what CPAY represents in Golink and the actual request schema
- [ ] Confirm customer authorization/approval flow and expiry
- [ ] Confirm approved/declined/pending mapping and finality

## EFT

- [ ] Confirm bank account/token requirements and whether debit initiation is supported
- [ ] Confirm settlement timing, cutoffs, returns and beneficiary verification
- [ ] Confirm pending transactions do not trigger premature ledger credits

## PAYSLIP

- [ ] Confirm product semantics, employer authorization and source-of-funds constraints
- [ ] Confirm payroll instruction references, settlement timing and reversals
- [ ] Confirm employer/employee personal data controls and retention policy

## Evidence log (fill only with real sandbox results)

| Rail | Provider schema reference | Redacted sandbox case | Webhook proof | Reconciliation proof | Approved by | Status |
|---|---|---|---|---|---|---|
| CARD | Pending | Pending | Pending | Pending | Pending | BLOCKED |
| CPAY | Pending | Pending | Pending | Pending | Pending | BLOCKED |
| EFT | Pending | Pending | Pending | Pending | Pending | BLOCKED |
| PAYSLIP | Pending | Pending | Pending | Pending | Pending | BLOCKED |

## Activation policy

1. Keep `GOLINK_COLLECTIONS_ENABLED` off in production until existing
   collection rail certification is completed.
2. These additional rails have **no active registration**. Their draft models
   do not confer permission to route payments.
3. Do not change `RAIL_CERTIFICATION` flags based on documentation alone.
   They require observed sandbox evidence and explicit code review.
4. A future execution implementation must be separate from the draft stub,
   undergo a PCI/security review where appropriate and have both negative and
   positive end-to-end tests before activation.
5. Preserve IthutePay's direct integrations, including direct M-PESA, and
   maintain the ability to disable or remove Golink without changing merchants.
