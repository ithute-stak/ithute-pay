# Architecture

## Separation of responsibilities

### Ithute Pay Bridge owns

- Provider authentication and credentials.
- Provider API calls.
- Provider transaction identity.
- Idempotency.
- Callback processing.
- Unknown-outcome recovery.
- Reversals.
- Direct-debit mandates.
- Hosted checkout/payment links.
- Gateway events/webhooks.
- Provider clearing ledger and reconciliation evidence.

### LoanHub owns

- Borrowers.
- Loan applications.
- Loan approval and contracts.
- Repayment allocation to principal/interest/fees/penalties.
- Loan schedule changes.
- Loan balances.
- Branch treasury/accounting.
- Loan receipt/document generation.

Ithute Pay Bridge metadata can carry `loan_id`, `borrower_id`, `branch_id` and other client-owned identifiers without interpreting them.

## Transaction state

Typical collection lifecycle:

```
created -> processing -> succeeded
                   \-> failed
                   \-> unknown -> provider query -> succeeded/failed
```

Provider request acceptance must not be treated as final settlement when the provider indicates asynchronous processing.

## Idempotency

Every creation endpoint that can move or reserve money requires `Idempotency-Key`. The gateway scopes the key to the merchant application and operation. Reusing a key with a different payload returns `409`.

## Webhooks

Events are persisted before delivery. Each configured endpoint receives a signed request containing:

```
X-IPB-Signature: t=<unix>,v1=<hmac-sha256>
X-IPB-Event: payment.succeeded
X-IPB-Event-ID: evt_...
```

Delivery attempts are retained and retried by Celery workers.


## Source organization

The FastAPI source follows the LoanHub-style separation of configuration/session/models/schemas, cross-cutting core services, route modules, versioned API registration, business services and provider integrations. This is a source-organization alignment only; Ithute Pay Bridge remains a standalone payment gateway.

## Realtime operations

The platform dashboard can establish a short-lived WebSocket session through `POST /api/v1/auth/websocket-session`, then connect to `/api/v1/ws`. Persisted gateway events remain the durable record; WebSockets are a low-latency UI channel and Redis can fan events across API workers.
