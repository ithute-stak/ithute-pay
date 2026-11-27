# Pass-through commercial accounting and release gates

## Approved design assumptions (not provider certification)

Default IthutePay rates: C2B 1%, B2C/B2B 2%; approved merchant-specific agreements override defaults. Incoming provider deduction assumed 1%; intermediate transfer charges must be confirmed separately. Existing direct M-Pesa remains independent.

| Example | Sender debit | Recipient credit | Platform fee |
|---|---:|---:|---:|
| C2B | M1,000 | M980 | M10 |
| B2C | M1,020 | M1,000 | M20 |
| B2B | M1,020 | M1,000 | M20 |

C2B assumes M10 deducted on funding and zero onward charge; outgoing assumes no additional provider cost on either leg. These are examples, not verified wallet balances.

## Journal contracts

Outgoing: confirmed funding Dr clearing / Cr payable M1,020; confirmed payout Dr payable / Cr clearing M1,000; earned fee Dr payable / Cr revenue M20. A confirmed eligible full refund instead debits payable and credits clearing M1,020, with no fee earned.

Incoming: confirmed gross funding Dr clearing / Cr payable M1,000; verified provider deduction Dr payable / Cr clearing M10; confirmed onward Dr payable / Cr clearing M980; earned fee Dr payable / Cr revenue M10. No fee before onward success. Incoming refunds remain blocked; fee recovery capacity preview is not authorization.

Use only trusted internal reconciliation, matching reserved operation, immutable parties, provider identity, currency, amount and actual fee/net credit evidence. Live successful legs require cost evidence. Commit evidence and journals atomically. Unknown outcomes require reconciliation, never blind retry. Accounting totals are not proof of provider float.

## Reversals

An authenticated reversal observation matching the original confirmed receipt creates an investigation hold. Original journals remain intact. New reservations, reconciliation and direct accounting replay are blocked. Do not silently rewrite balances, post a compensating entry or treat reversal as a refund. Before implementing financial adjustments obtain the original and reversal identifiers, actual credited/debited amounts, fee recovery, final status, beneficiary impact, loss-bearing party and approved adjustment rules. Confirm no duplicate recovery or later conflicting payout. Independent review must approve any eventual compensating journal; hold release is not currently implemented.

## Release gates (not satisfied by green CI alone)

- [ ] Confirm Vodacom Lesotho authorizes master-shortcode pass-through, merchant-specific settlement and automatic fee retention; obtain applicable legal/regulatory approval.
- [ ] Confirm actual C2B, funding B2B, onward B2B/B2C, refund and reversal tariffs, including sender-side charges and nonrefundable deductions.
- [ ] Obtain authenticated sandbox query and settlement evidence with exact field mappings for original reference, parties, currency, amount, final status, provider ID, actual net credit, provider costs and source debit.
- [ ] Certify provider evidence retrieval and credential scope; do not infer missing values from quote or response code.
- [ ] Certify refund and reversal adjustment rules, independent review, audit trail and hold release.
- [ ] Implement and certify durable dispatch and reconciliation worker, unknown-outcome recovery, idempotency and environment isolation before live execution.
- [ ] Run isolated end-to-end provider certification and reconcile against statements; confirm no duplicate money movements and correct fee retention.
- [ ] Verify database migrations and restore drill, authorization, reporting isolation and direct M-Pesa regression on the exact release.
- [ ] Obtain approved deployment and rollback plan, financial/security sign-off and explicit activation approval.

Keep live pass-through disabled. A successful CI run establishes only the tests it executed. The direct M-Pesa integration is not part of this activation.


## Provider certification handoff

Use a disposable test application and explicitly approved sandbox accounts. Do not use production credentials, actual customer numbers or real funds for these tests. Never store API keys, session tokens or unredacted customer information in CI artifacts.

| Test | Expected sender debit | Expected recipient credit | Expected deduction |
|---|---:|---:|---:|
| C2B customer to gateway | 1000.00 | 990.00 | 10.00 |
| C2B gateway to merchant | 980.00 | 980.00 | 0.00 |
| B2C merchant to gateway | 1020.00 | 1020.00 | 0.00 |
| B2C gateway to customer | 1000.00 | 1000.00 | 0.00 |
| B2B merchant to gateway | 1020.00 | 1020.00 | 0.00 |
| B2B gateway to recipient merchant | 1000.00 | 1000.00 | 0.00 |

These amounts are hypothetical certification targets, not observed provider results. If the provider charges differently, stop and review commercial agreements and allocation rules before continuing.

For each operation capture the original reference, provider transaction identifier, authenticated account scope, final status, currency, source debit, destination credit, deducted fee and statement reconciliation reference. Preserve redacted evidence with the exact release commit and independent reviewer approval. A generic accepted response is insufficient; missing evidence is a blocker, not zero cost. Sender debit evidence is mandatory for live reconciliation, live journal posting and onward reservation. Existing direct M-Pesa must remain independent.

Offline CI exercises request serialization through the existing client with an overridden network transport, persistent worker claims, duplicate confirmation and PostgreSQL races. It does not perform a real sandbox transaction. The adapter argument builder returns dispatch_authorized=false. Reserved or ambiguous operations must only be queried, never automatically submitted. No actual pass-through sender or public execution endpoint is enabled. Reversal holds remain manual pending verified compensation rules.

Release decision: the pricing, preview and reporting foundation may be considered separately for a disabled-feature release after exact-commit CI and review. Live activation is a separate decision and must not be implied by merging or deploying the foundation.
