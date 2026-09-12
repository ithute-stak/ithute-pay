# Security model

## Platform users

Passwords use Argon2. Login issues short-lived access cookies and rotating refresh sessions. Refresh token values are not stored: only SHA-256 hashes are persisted. Cookie-authenticated state-changing requests require the `ipb_csrf` double-submit token.

## Merchant applications

Merchant keys use the `ipb_test_` / `ipb_live_` namespaces. Only their hash, prefix and last four characters are stored. The full secret is returned once when created.

Every operation capable of creating/reserving/moving money requires an idempotency key. Reusing a key with different content is rejected with conflict instead of creating another financial action.

## Optional signed requests

HMAC-SHA256 signing binds timestamp, one-time nonce, HTTP method, request path and SHA-256 body hash. Redis stores accepted nonces during the signature window to prevent replay.

## Provider secrets

M-Pesa API keys are encrypted before persistence. Session keys remain server-side. Provider credentials are never placed in `NEXT_PUBLIC_*` variables. Customer M-Pesa PIN entry occurs only through the provider channel.

## Webhooks

Merchant webhook endpoints receive timestamped HMAC signatures. Deliveries are durable, retried and replayable. External systems should deduplicate on event ID and reject stale signature timestamps.

## Browser console

Next.js uses `credentials: include`, HttpOnly auth cookies, CSRF headers and Redux RTK Query. Access tokens are not stored in localStorage. WebSocket access uses a short-lived HttpOnly socket session cookie.

## Financial safety

- Unknown/time-out provider results are reconciled; they are not blindly re-sent.
- Reversals are compensating transactions and journal entries.
- Double-entry journals reject unbalanced postings.
- Settlement requests cannot exceed the merchant payable balance.
- Provider callback processing is idempotent through stored provider operations/transactions.
- PostgreSQL is the source of truth for financial records; Redis is coordination/cache only.

## Production hardening

Run TLS before using live credentials and set `AUTH_COOKIE_SECURE=true`. Restrict PostgreSQL/Redis to internal networks, rotate credentials, use least-privilege GHCR/VPS credentials, and restrict provider callbacks by trusted ingress ranges when the provider publishes them.
