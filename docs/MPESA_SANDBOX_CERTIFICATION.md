# M-Pesa Sandbox Certification

IthutePayBridge includes a provider-specific M-Pesa certification surface under:

- `GET /api/v1/admin/testing/mpesa-certification/catalog`
- `POST /api/v1/admin/testing/mpesa-certification/run`
- `POST /api/v1/admin/testing/mpesa-certification/run-suite`

The certification runner is **sandbox-only**. It refuses a production M-Pesa provider configuration and uses the same centrally configured, hardened M-Pesa gateway adapter used by normal PayBridge traffic.

## Why this exists

The M-Pesa Developer Portal publishes deterministic Sandbox trigger values for C2B, B2C, B2B, Query Transaction Status, Reversal, Update Transaction Status and Direct Debit operations. PayBridge keeps these triggers as provider test data rather than weakening production validation rules.

## Response handling policy

PayBridge intentionally distinguishes business failures from uncertain transport/provider states:

- HTTP 200/201 + provider success: succeeded, or processing when M-Pesa accepted an asynchronous operation without terminal evidence.
- HTTP 401 transaction failure: failed. A financial request is not automatically replayed merely because the HTTP status is 401.
- HTTP 408 timeout: unknown and requires reconciliation/query.
- HTTP 422 insufficient balance: failed business outcome.
- HTTP 500 internal error: unknown and requires reconciliation unless the provider returned a known deterministic business validation code.

## Direct Debit Payment sandbox MSISDN exception

The official Direct Debit Payment Sandbox triggers are 20 digits long:

- `00000000000000000001` success
- `00000000000000000002` internal error
- `00000000000000000003` transaction failed
- `00000000000000000004` request timeout
- `00000000000000000005` service unavailable

These values are accepted only when all of the following are true:

1. M-Pesa environment is `sandbox`.
2. The request is `directDebitPayment/`.
3. The MSISDN exactly matches one of the provider-published trigger values above.

They remain invalid in production and on every other M-Pesa endpoint.

## Update Transaction Status

The provider testing table supplies deterministic TransactionID values, but the API operation also requires a valid VoucherCode from a prior multi-stage C2B authorization. The certification runner therefore requires `voucher_code` for Update Transaction Status and does not invent one.

## Query Transaction Status v3.1 and Query Beneficiary Name

The supplied Sandbox testing page lists trigger values for these operations but does not establish enough information to safely send them from the Lesotho gateway:

- Query Transaction Status v3.1: the exact v3.1 wire contract is not established by the testing page alone.
- Query Beneficiary Name: the testing page alone does not confirm `vodacomLES` product availability.

They are shown in the certification catalog as `documented_not_runnable` instead of being guessed or silently enabled.

## USSD Push simulation

For a real Sandbox USSD Push, register the test MSISDN in the M-Pesa Developer Portal TEST MSISDN page, then use that number as the phone override in the existing PayBridge Collections live-sandbox test. The provider controls the 30-day TEST MSISDN change restriction.

## Example single certification case

```json
{
  "product": "c2b",
  "scenario": "insufficient_balance",
  "amount": "25.00",
  "currency": "LSL"
}
```

## Example full executable suite

```json
{
  "amount": "25.00",
  "currency": "LSL"
}
```

If the M-Pesa application does not have a product capability enabled, that product is skipped/rejected rather than called. Update Transaction Status is skipped in a suite unless a valid Sandbox VoucherCode is supplied.
