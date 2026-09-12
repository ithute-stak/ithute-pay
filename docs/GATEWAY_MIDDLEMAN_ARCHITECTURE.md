# Ithute Pay Bridge — M-Pesa Middleman Gateway Architecture

## Purpose

Ithute Pay Bridge is the merchant-facing payment gateway. Client systems such as schools, micro-lenders, insurers and retailers integrate with Ithute Pay Bridge rather than storing the gateway's Vodacom M-Pesa credentials themselves.

For a routed collection the money flow is:

```text
Customer M-Pesa wallet
        |
        | C2B gross amount
        v
Ithute Pay Bridge M-Pesa merchant
        |
        |-- gateway fee -> Ithute Pay Bridge revenue
        |
        `-- net amount -> client M-Pesa merchant/MSISDN (B2B/B2C settlement)
```

The accounting flow is double-entry and the provider movement is independently auditable.

## Environment management

The database table `gateway_provider_configurations` owns runtime M-Pesa configuration. A sandbox row is seeded automatically with Lesotho defaults:

- provider: `mpesa`
- environment: `sandbox`
- market: `vodacomLES`
- country: `LES`
- currency: `LSL`
- mode: `simulator` by default

Production credentials are entered from **Dashboard -> Providers** and are encrypted at rest. Only one environment per provider is active at a time. `.env` remains the bootstrap/fallback configuration, not the normal place to switch production payment modes.

Never put the M-Pesa API key in Next.js, mobile apps, school systems or client databases.

## Provider-facing URLs

The gateway stores and displays four URLs per provider environment:

| URL | Purpose |
| --- | --- |
| Callback URL | Receives asynchronous payment/provider results |
| Result URL | Receives final results for flows that distinguish a result endpoint |
| Queue timeout URL | Records an uncertain/timeout result for reconciliation |
| Redirect/return URL | Browser return destination only; never considered authoritative proof of payment |

Default routes:

```text
POST /api/v1/provider-callbacks/mpesa/callback
POST /api/v1/provider-callbacks/mpesa/result
POST /api/v1/provider-callbacks/mpesa/timeout
GET  /api/v1/provider-callbacks/mpesa/return
```

The callback/result bodies are normalized from Vodacom M-Pesa OpenAPI fields. A timeout marks the transaction/operation `unknown`; the reconciliation worker queries M-Pesa instead of issuing a second payment.

## Client routing

A client organization has:

- a Merchant record;
- an Application used for API/webhook ownership;
- a `MerchantGatewayProfile` with sector, merchant number and settlement policy;
- zero or more routing identifiers (`school_number`, `company_number`, etc.);
- one or more M-Pesa settlement accounts;
- an optional assigned commercial fee package;
- signed webhook endpoints back into the client's platform.

The generic routed collection endpoint is:

```text
POST /api/v1/public/routed-collections
```

Example school request:

```json
{
  "merchant_number": "SCH-001",
  "customer_reference": "STU-2026-0007",
  "phone": "+26659001234",
  "amount": "500.00",
  "currency": "LSL",
  "reference": "TERM-3-FEES",
  "reason": "Term 3 tuition",
  "idempotency_key": "school-payment-2026-0007-1"
}
```

`customer_reference` is intentionally sector-neutral:

- school: student number;
- micro-loan: borrower or loan number;
- insurance: policy/member number;
- retail/invoice: customer or invoice number.

The same values are promoted into the signed merchant webhook event, so a school can update the correct student without exposing M-Pesa credentials to the school.

## Signed client notification

On a confirmed payment the client receives a normal Ithute Pay Bridge webhook event such as `payment.succeeded`.

The event data includes at least:

```json
{
  "id": "pi_...",
  "status": "succeeded",
  "amount": "500.00",
  "currency": "LSL",
  "merchant_number": "SCH-001",
  "customer_reference": "STU-2026-0007",
  "reference": "TERM-3-FEES",
  "reason": "Term 3 tuition",
  "settlement": {
    "gross_amount": "500.00",
    "fee_amount": "7.00",
    "net_amount": "493.00",
    "status": "pending"
  }
}
```

Client systems must verify the Ithute Pay Bridge webhook signature and make their webhook handler idempotent. The authoritative update chain is:

```text
M-Pesa -> Ithute Pay Bridge callback/reconciliation
        -> Ithute Pay Bridge database/ledger
        -> signed client webhook
        -> client backend/database
        -> client's WebSocket/SSE
        -> client frontend
```

The payment gateway should not directly mutate or notify a client's browser. The client's backend remains authoritative for the client's domain records.

## Fees

Commercial packages support rules for:

- collection/direct debit;
- payout;
- B2B transfer.

A rule can use:

- fixed fee;
- percentage fee;
- minimum fee;
- maximum fee.

Fee lookup priority is:

1. explicit legacy merchant override;
2. assigned merchant fee package;
3. legacy global override;
4. default fee package;
5. zero fee.

For an inbound collection:

```text
Gross = customer payment
Fee   = gateway commercial charge
Net   = Gross - Fee
```

The ledger records gross provider clearing, net merchant payable and gateway fee revenue. A separate `SettlementInstruction` sends the net amount to the client's configured M-Pesa destination and removes the merchant payable only after the provider confirms the settlement.

## Settlement behavior

Settlement account types:

- `business_shortcode` -> M-Pesa B2B;
- `msisdn` -> M-Pesa B2C.

Merchant policy supports:

- automatic settlement;
- manual review (`ready`);
- settlement delay;
- disabled/held client;
- unconfigured destination detection.

A source collection can create only one settlement instruction, preventing duplicate provider payout attempts.

## M-Pesa services in the gateway

The adapter surface contains:

- Generate SessionKey;
- C2B Single Stage;
- C2B Multi Stage authorization;
- Update Transaction Status commit/uncommit;
- B2C payout;
- B2B transfer;
- Query Transaction Status;
- Reversal;
- Direct Debit Create;
- Query Direct Debit;
- Direct Debit Payment;
- Direct Debit Cancel.

Direct Debit Payment includes both amount and currency. Query Direct Debit can be used before charging to inspect mandate/account state and, when requested, sufficient balance.

## Real-time UI

Gateway events are queued until the database transaction commits, then broadcast over the existing WebSocket manager to platform, merchant and application channels. The Ithute Pay Bridge dashboard can therefore refresh after payment, settlement, mandate and provider state changes without polling.

For later LoanHub integration, the recommended path is Pay Bridge webhook -> LoanHub backend -> LoanHub database -> LoanHub WebSocket -> LoanHub frontend.

## Production rules

Before activating a live M-Pesa environment:

1. Configure HTTPS public callback/result/timeout URLs.
2. Configure the exact Origin registered with M-Pesa.
3. Store the live Application API Key using the Providers UI; never commit it.
4. Store the correct platform public key.
5. Configure the gateway service provider shortcode.
6. Configure client settlement destinations and fees.
7. Test success, timeout, incorrect PIN, insufficient balance, duplicate and reconciliation scenarios in sandbox.
8. Keep workers/Redis running for webhook delivery, transaction recovery and settlements.
9. Reconcile unknown results instead of blindly retrying financial movements.
