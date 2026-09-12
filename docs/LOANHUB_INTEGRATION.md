# LoanHub Integration Guide

LoanHub should call Ithute Pay Bridge only from the LoanHub FastAPI backend.

## 1. Create merchant application

In Ithute Pay Bridge create:

- Merchant: LoanHub
- Application: LoanHub Sandbox or LoanHub Production
- API key
- Webhook endpoint pointing to LoanHub FastAPI

Store the Ithute Pay Bridge API key and webhook signing secret as LoanHub backend secrets.

## 2. Repayment

LoanHub creates a payment intent and stores Ithute Pay Bridge's `pi_*` ID before waiting for provider confirmation.

Recommended metadata:

```json
{
  "loan_id": "internal-loan-id",
  "borrower_id": "internal-borrower-id",
  "branch_id": "internal-branch-id",
  "actor_user_id": "cashier-user-id"
}
```

On `payment.succeeded`, LoanHub should perform its existing repayment transaction exactly once using the Ithute Pay Bridge payment ID as an external idempotency reference.

## 3. Loan disbursement

LoanHub creates a payout only after its internal approval/contract requirements are satisfied. It should not mark the loan disbursed merely because Ithute Pay Bridge accepted the request. Wait for confirmed `payout.succeeded` or explicitly refresh the status.

## 4. Unknown status

Do not create a second payout/payment because of a timeout. Call the Ithute Pay Bridge status endpoint. Ithute Pay Bridge in turn uses the provider Query Transaction Status capability.

## 5. Direct debit

LoanHub can create a mandate after the borrower agrees to M-Pesa direct-debit terms. For monthly loans, send LoanHub's agreed first instalment date and payment-day range. Before charging, Ithute Pay Bridge can query mandate/account state and available balance.

## 6. Reversal

LoanHub requests a Ithute Pay Bridge reversal, then creates compensating loan/accounting entries only when the reversal is confirmed. Historical repayment/disbursement records must never be deleted.

## 7. Webhook verification

Use the raw request bytes and merchant webhook secret:

```
signed_payload = "<timestamp>." + raw_body
expected = HMAC_SHA256(secret, signed_payload)
```

Compare against `v1` in `X-IPB-Signature` and reject timestamps outside the configured tolerance.

## 8. Routed-gateway option

LoanHub can either use its private Ithute Pay Bridge API key to create payment intents/payouts directly, or use the generic routed collection model when a common payment form/gateway is desired.

For routed repayment, configure a LoanHub merchant number/routing key in Pay Bridge and use the borrower or loan number as `customer_reference`. The signed `payment.succeeded` webhook then contains that reference, amount, reason and settlement snapshot.

The LoanHub integration boundary should remain:

```text
M-Pesa
  -> Ithute Pay Bridge provider callback/reconciliation
  -> signed Ithute Pay Bridge webhook
  -> LoanHub FastAPI payment endpoint
  -> LoanHub PostgreSQL transaction/repayment posting
  -> LoanHub WebSocket broadcast
  -> LoanHub Next.js UI
```

This prevents a browser notification from becoming the source of truth for a loan payment. LoanHub should update a borrower/loan only after its backend has verified and idempotently accepted the signed gateway event.

Loan disbursement remains a B2C payout from Ithute Pay Bridge. Recurring repayments use Direct Debit Create -> Query -> Payment -> Cancel, subject to the borrower-approved mandate.
