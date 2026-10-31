# Golink Phase 5 — sandbox test cases

All cases are **pending provider evidence**. These are test plans, not verified Golink API behavior.
Run in a dedicated sandbox only, with provider-issued test credentials. Never use live payment details, real card numbers or production API keys.

## Prerequisites

1. Obtain the official provider API contract/version, rail-specific schemas and supported operations.
2. Confirm callback authentication, retry and reconciliation endpoints with Golink.
3. Use isolated test merchants/accounts and provider-authorized sandbox identities.
4. Store redacted evidence outside source control. Record case IDs and a cryptographic hash or restricted evidence location, never keys, tokens, raw cards, bank details or personal identity information.
5. Validate failures as well as successes before changing any certification status.

## Test matrix — run independently for CARD, CPAY, EFT and PAYSLIP

| ID | Case | Expected IthutePay behavior | Evidence required |
|---|---|---|---|
| P5-01 | Unsupported rail or missing certification | Reject before any external operation | Application test and audit event |
| P5-02 | Invalid required field / unsupported currency | Reject locally or map provider validation error without ledger mutation | Redacted request schema and response code |
| P5-03 | Idempotent retry with same intent | Reuse original identity, never duplicate collection | Provider attempt references and matching outcomes |
| P5-04 | Same idempotency key, changed intent | Quarantine/reject conflict | Redacted conflict response |
| P5-05 | Timeout after ambiguous submission | Do not resubmit blindly; reconcile original intent | Recorded retry and read-back outcome |
| P5-06 | Pending or user action required | Do not book a completed payment | Status transitions and audit timeline |
| P5-07 | Verified success webhook | Verify authenticity and reconcile provider record before posting | Signed callback sample with secrets removed; authenticated read-back |
| P5-08 | Forged/replayed/out-of-order webhook | Reject or safely deduplicate, no duplicate ledger entries | Replay test and ledger assertions |
| P5-09 | Failed/rejected/expired transaction | Correct terminal state, no false success posting | Provider status and accounting checks |
| P5-10 | Provider reconciliation mismatch | Quarantine and alert; do not settle | Mismatch on rail, amount, currency or reference |
| P5-11 | Simultaneous terminal notifications | At most one terminal state and journal posting | PostgreSQL concurrent-worker evidence |
| P5-12 | Disable Golink while another direct rail is active | Existing direct M-PESA/EcoCash unaffected | Routing and rollback tests |
| P5-13 | Merchant/tenant isolation | No cross-tenant reads or writes | Authorization assertions |
| P5-14 | Refund/reversal/chargeback if supported | Only documented and approved flows | Provider authorization and matching settlement records |

## Rail-specific cases

**CARD:** Hosted/tokenized checkout (no PAN/CVV retained), 3-D Secure if applicable, authorization versus capture, settlement/chargebacks, browser return versus independent webhook proof.

**CPAY:** Provider-defined authorization, mandate/reference, expiration, pending/declined/completed outcomes. Do not assume CPAY semantics before Golink confirms them.

**EFT:** Supported bank transfer direction, beneficiary data requirements, cutoffs, asynchronous settlement, returns and finality.

**PAYSLIP:** Confirm actual product definition, employer/payroll authorization, payroll reference, failed deduction, settlement and reversal rules. No employee personal information in test evidence.

## Certification sign-off (separate for each rail)

| Rail | Official contract | Happy-path evidence | Failure/timeout evidence | Security review | Reconciliation + ledger | Authorized reviewer | Decision |
|---|---|---|---|---|---|---|---|
| CARD | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | BLOCKED |
| CPAY | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | BLOCKED |
| EFT | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | BLOCKED |
| PAYSLIP | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | BLOCKED |

The existing draft executor remains deliberately non-executable. Activation requires a separate, reviewed implementation with positive and negative integration tests, in addition to this evidence.
