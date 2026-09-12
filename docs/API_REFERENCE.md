# Ithute Pay Bridge API reference

Base URL on the configured VPS: `http://169.255.58.185:8081/api/v1`.

Interactive OpenAPI: `/docs`.

## Authentication

### Platform console

- `POST /auth/login`
- `POST /auth/refresh`
- `POST /auth/logout`
- `GET /auth/me`
- `POST /auth/websocket-session`
- `WS /ws`

The browser console uses HttpOnly access/refresh cookies plus an `ipb_csrf` double-submit token.

### Merchant systems

Use `Authorization: Bearer ipb_test_...` or `ipb_live_...`. Financial create calls require `Idempotency-Key`. Optional request signing uses `X-IPB-Timestamp`, `X-IPB-Nonce`, and `X-IPB-Signature`.

## Collections

- `POST /payment-intents`
- `GET /payment-intents`
- `GET /payment-intents/{payment_id}`
- `POST /payment-intents/{payment_id}/confirm`
- `POST /payment-intents/{payment_id}/cancel`
- `POST /payment-intents/{payment_id}/refresh-status`

## Payouts

- `POST /payouts`
- `GET /payouts`
- `GET /payouts/{payout_id}`
- `POST /payouts/{payout_id}/refresh-status`

## B2B transfers

- `POST /transfers`
- `GET /transfers`
- `GET /transfers/{transfer_id}`

## Provider transactions and reversals

- `GET /transactions`
- `GET /transactions/{transaction_id}`
- `POST /transactions/{transaction_id}/refresh-status`
- `POST /transactions/{transaction_id}/reversals`
- `GET /reversals`
- `GET /reversals/{reversal_id}`

A successful reversal creates a compensating journal. Historical transaction/accounting rows are not deleted.

## Two-stage collection authorizations

- `POST /authorizations`
- `GET /authorizations`
- `GET /authorizations/{authorization_id}`
- `POST /authorizations/{authorization_id}/commit`
- `POST /authorizations/{authorization_id}/release`

## Direct debit

- `POST /mandates`
- `GET /mandates`
- `GET /mandates/{mandate_id}`
- `POST /mandates/{mandate_id}/refresh`
- `POST /mandates/{mandate_id}/charges`
- `GET /mandates/{mandate_id}/charges`
- `POST /mandates/{mandate_id}/cancel`

## Hosted checkout

- `POST /checkout-sessions`
- `GET /checkout-sessions`
- `GET /checkout-sessions/{session_id}`
- `GET /public/checkout-sessions/{token}`
- `POST /public/checkout-sessions/{token}/pay`

## Payment links

- `POST /payment-links`
- `GET /payment-links`
- `GET /payment-links/{link_id}`
- `GET /public/payment-links/{token}`
- `POST /public/payment-links/{token}/pay`

## Merchant accounting

- `GET /finance/balance`
- `GET /finance/accounts`
- `GET /finance/trial-balance`
- `GET /finance/journal`
- `GET /finance/ledger`
- `POST /finance/settlement-requests`
- `GET /finance/settlement-requests`

## Merchant developer operations

- `GET /developer/events`
- `GET /developer/webhook-endpoints`
- `POST /developer/webhook-endpoints`
- `POST /developer/webhook-endpoints/{webhook_id}/disable`
- `GET /developer/webhook-deliveries`
- `POST /developer/webhook-deliveries/{delivery_id}/replay`

## Provider callback

- `POST /provider-callbacks/mpesa`

This endpoint is provider-facing. It is not a merchant API.

## Platform administration

Platform roles operate `/admin/*` endpoints for merchants, applications/API keys, payments, payouts, transfers, authorizations, reversals, transactions, mandates, checkout sessions, payment links, provider configurations, webhooks/events, fees, settlements, accounting, reconciliation and audit logs.

## Collection example

```http
POST /api/v1/payment-intents
Authorization: Bearer ipb_test_xxx
Idempotency-Key: order-445-payment-1
Content-Type: application/json
```

```json
{
  "amount": "600.00",
  "currency": "LSL",
  "provider": "mpesa",
  "payment_method": "mobile_money",
  "customer": {"phone": "26659001234"},
  "reference": "ORDER-445",
  "description": "Customer payment",
  "metadata": {"external_id": "445"},
  "confirm": true
}
```

Do not create a new request merely because a network response is uncertain. Reuse the internal resource and refresh transaction status.

## Platform sandbox testing

Platform administrators can use the built-in simulator test lab:

```http
GET  /api/v1/admin/testing/catalog
POST /api/v1/admin/testing/run
POST /api/v1/admin/testing/run-all
GET  /api/v1/admin/testing/history
```

The test lab always uses a system-managed `test` application with the provider adapter forced to `simulator` mode. See `docs/SANDBOX_TESTING_GUIDE.md`.
