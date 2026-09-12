# Ithute Pay Bridge — Consumer Integration Guide

This handbook is for systems that consume Ithute Pay Bridge: LoanHub, POS systems, insurers, e-commerce platforms, mobile applications with a trusted backend, ERP systems and other business services.

A consumer should integrate **server-to-server**. Never embed a Pay Bridge API key in browser JavaScript, a public mobile binary or a public Git repository.

## 1. Environment and base URL

Your administrator supplies:

- a Pay Bridge base URL, such as `https://pay.example.com`;
- a `test` or `live` application;
- an API key shown only once when it is created;
- webhook signing secret(s) when webhooks are configured.

Credential prefixes:

```text
ipb_test_... -> sandbox / UAT application
ipb_live_... -> production application
```

Test and live applications are separate identities. Never use a live key while running simulator/UAT tests.

## 2. API authentication

Send the application key as a Bearer token:

```http
Authorization: Bearer ipb_test_REPLACE_ME
```

A missing, revoked or inactive application key returns an authentication error.

## 3. Idempotency for financial creates

Financial create operations require:

```http
Idempotency-Key: <stable-key-for-this-intended-business-operation>
```

Generate the key from a durable business operation or store a generated UUID with that operation. When an HTTP response is lost, retry with **the same key**. Do not create a new key just because the request timed out.

Examples:

```text
loan-410-disbursement-1
invoice-920-collection-1
policy-2026-001-july-premium
```

Persist together:

```text
your business reference
idempotency key
Pay Bridge public resource ID
current status
provider transaction reference when available
```

## 4. Optional HMAC request signing

Pay Bridge can require signed merchant requests. Headers:

```http
X-IPB-Timestamp: <unix-seconds>
X-IPB-Nonce: <unique-random-value>
X-IPB-Signature: sha256=<hex-hmac>
```

Canonical byte content:

```text
<timestamp>\n<nonce>\n<METHOD>\n<PATH>\n<SHA256(raw-body)>
```

The HMAC algorithm is SHA-256 and the key is the full application API-key secret. The path is the request URL path, for example `/api/v1/payment-intents`.

Python helper:

```python
import hashlib
import hmac
import json
import secrets
import time

api_key = "ipb_test_REPLACE_ME"
method = "POST"
path = "/api/v1/payment-intents"
payload = {"amount": "125.00", "currency": "LSL"}
raw_body = json.dumps(payload, separators=(",", ":")).encode()

timestamp = str(int(time.time()))
nonce = secrets.token_urlsafe(18)
body_hash = hashlib.sha256(raw_body).hexdigest()
canonical = f"{timestamp}\n{nonce}\n{method}\n{path}\n{body_hash}".encode()
signature = hmac.new(api_key.encode(), canonical, hashlib.sha256).hexdigest()

headers = {
    "Authorization": f"Bearer {api_key}",
    "X-IPB-Timestamp": timestamp,
    "X-IPB-Nonce": nonce,
    "X-IPB-Signature": f"sha256={signature}",
}
```

The server validates the timestamp window and rejects a reused nonce when replay storage is available.

## 5. Collections

Create a customer-to-business mobile-money collection:

```http
POST /api/v1/payment-intents
```

```bash
curl -X POST 'https://pay.example.com/api/v1/payment-intents' \
  -H 'Authorization: Bearer ipb_test_REPLACE_ME' \
  -H 'Idempotency-Key: order-410-payment-1' \
  -H 'Content-Type: application/json' \
  -d '{
    "amount": "125.00",
    "currency": "LSL",
    "provider": "mpesa",
    "payment_method": "mobile_money",
    "customer": {"phone": "26658000001", "name": "Test Customer"},
    "reference": "ORDER-410",
    "description": "Order payment",
    "metadata": {"order_id": "410"},
    "confirm": true
  }'
```

Important collection operations:

```http
POST /api/v1/payment-intents
GET  /api/v1/payment-intents
GET  /api/v1/payment-intents/{payment_id}
POST /api/v1/payment-intents/{payment_id}/confirm
POST /api/v1/payment-intents/{payment_id}/cancel
POST /api/v1/payment-intents/{payment_id}/refresh-status
```

## 6. Payouts

Use a payout for business-to-customer disbursement:

```http
POST /api/v1/payouts
```

Example body:

```json
{
  "amount": "75.00",
  "currency": "LSL",
  "provider": "mpesa",
  "destination_phone": "26658000001",
  "reference": "CLAIM-190-PAYOUT",
  "description": "Claim settlement",
  "metadata": {"claim_id": "190"}
}
```

Use `/payouts/{id}/refresh-status` instead of creating a duplicate payout when the provider outcome is uncertain.

## 7. Business transfers

```http
POST /api/v1/transfers
```

Use this for B2B movement to a provider business/service code. Supply `receiver_party_code` and your own stable `reference`.

## 8. Two-stage authorization

```http
POST /api/v1/authorizations
POST /api/v1/authorizations/{id}/commit
POST /api/v1/authorizations/{id}/release
```

Use this when funds must be authorized first and captured later. Do not treat `authorized` as the same business state as a committed `succeeded` collection.

## 9. Direct debit mandates

```http
POST /api/v1/mandates
GET  /api/v1/mandates/{id}
POST /api/v1/mandates/{id}/refresh
POST /api/v1/mandates/{id}/charges
GET  /api/v1/mandates/{id}/charges
POST /api/v1/mandates/{id}/cancel
```

The mandate reference must be alphanumeric and up to 32 characters. Store the Pay Bridge mandate ID against the customer/subscription in your own system.

## 10. Hosted checkout

```http
POST /api/v1/checkout-sessions
```

The response contains a hosted checkout URL/token. Redirect the customer to that Pay Bridge page. The consumer backend remains responsible for confirming the final status through API/webhook rather than trusting a browser redirect alone.

Public checkout routes are token-based and do not require a merchant API key:

```http
GET  /api/v1/public/checkout-sessions/{token}
POST /api/v1/public/checkout-sessions/{token}/pay
```

## 11. Payment links

```http
POST /api/v1/payment-links
```

The response contains a shareable Pay Bridge payment URL. A link can be configured as reusable. Consumer systems should still reconcile payments using Pay Bridge resource IDs and their own reference/metadata.

## 12. Transaction status and reversals

```http
GET  /api/v1/transactions
GET  /api/v1/transactions/{transaction_id}
POST /api/v1/transactions/{transaction_id}/refresh-status
POST /api/v1/transactions/{transaction_id}/reversals
GET  /api/v1/reversals
GET  /api/v1/reversals/{reversal_id}
```

A reversal creates compensating accounting records; it does not erase the original transaction history.

## 13. Resource states

Consumers should be prepared for asynchronous states. Depending on product, important values include:

```text
created
requires_confirmation
awaiting_customer
processing
unknown
succeeded
failed
expired
cancelled
reversed
partially_reversed
```

Only a terminal success/reversal state should drive irreversible downstream business actions. A timeout or `processing`/`unknown` status is not evidence that a new payment should be created.

## 14. Accounting and settlement APIs

For merchant financial visibility:

```http
GET  /api/v1/finance/balance
GET  /api/v1/finance/accounts
GET  /api/v1/finance/trial-balance
GET  /api/v1/finance/journal
GET  /api/v1/finance/ledger
POST /api/v1/finance/settlement-requests
GET  /api/v1/finance/settlement-requests
```

Pay Bridge uses double-entry accounting. Consumer systems should not try to calculate the authoritative Pay Bridge balance only from payment rows.

## 15. Webhooks

Webhooks are the durable asynchronous integration channel. WebSocket messages are intended for realtime dashboard experience, not as the only source of truth for an external consumer.

Delivery headers:

```http
X-IPB-Signature: t=<timestamp>,v1=<hex-digest>
X-IPB-Event: payment.succeeded
X-IPB-Event-ID: evt_xxxxx
```

The exact bytes signed are:

```text
<timestamp>.<raw JSON request body>
```

Python verification example:

```python
import hashlib
import hmac


def verify_ipb_webhook(raw_body: bytes, signature_header: str, signing_secret: str) -> bool:
    parts = dict(part.split("=", 1) for part in signature_header.split(","))
    timestamp = parts["t"]
    supplied = parts["v1"]
    signed = timestamp.encode() + b"." + raw_body
    expected = hmac.new(signing_secret.encode(), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, supplied)
```

Webhook consumer rules:

1. read the raw request body;
2. verify HMAC before trusting parsed data;
3. persist `X-IPB-Event-ID` and make event processing idempotent;
4. return 2xx quickly;
5. perform expensive business work asynchronously;
6. tolerate duplicate delivery;
7. never use the browser redirect as the payment authority.

## 16. Sandbox simulator

Deterministic test phone numbers:

```text
26658000001 -> succeeded
26658000002 -> failed / insufficient funds
26658000003 -> processing / unknown
```

The administrator can validate the gateway itself from **Dashboard → Sandbox test lab** before your integration begins.

## 17. Error handling

Typical HTTP status meaning:

```text
400  missing/invalid idempotency input or invalid operation request
401  missing/invalid/revoked credential or invalid signature
403  permission/scope restriction
404  resource not visible/not found
409  state conflict, nonce reuse or idempotency conflict
422  schema/business validation failure
429  rate limited
5xx  gateway/provider/infrastructure failure
```

For financial operations, retry network/5xx uncertainty only with the same idempotency key unless you have positively established that a new business operation is intended.

## 18. Server-side TypeScript example

```ts
const response = await fetch(`${PAYBRIDGE_URL}/api/v1/payment-intents`, {
  method: "POST",
  headers: {
    Authorization: `Bearer ${PAYBRIDGE_API_KEY}`,
    "Idempotency-Key": `invoice-${invoice.id}-payment-1`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    amount: invoice.amount.toFixed(2),
    currency: "LSL",
    provider: "mpesa",
    payment_method: "mobile_money",
    customer: { phone: customer.phone },
    reference: invoice.reference,
    confirm: true,
  }),
});

if (!response.ok) {
  throw new Error(`Pay Bridge HTTP ${response.status}: ${await response.text()}`);
}

const payment = await response.json();
```

Keep `PAYBRIDGE_API_KEY` in a backend secret store. Do not use `NEXT_PUBLIC_*` for it.

## 19. Go-live checklist for consumers

- test application integration completed
- idempotency retry tested
- HMAC request signing tested when enabled
- success, insufficient-funds and processing states tested
- webhook raw-body signature verification tested
- duplicate webhook event tested
- Pay Bridge IDs persisted with internal references
- timeout behavior does not create duplicate money movement
- live URL uses HTTPS
- live key stored server-side only
- controlled live transaction completed
- webhook delivery confirmed
- reconciliation checked with administrator
