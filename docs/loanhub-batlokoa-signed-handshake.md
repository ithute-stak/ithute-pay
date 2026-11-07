# LoanHub ↔ IthutePay: read-only signed handshake (off by default)

This stage adds a dedicated service-to-service endpoint for the **existing** Batlokoa LoanHub company and IthutePay master merchant shortcode 38542. It does not create a merchant, issue API keys, activate the inactive application, enable payment routing, change fee posting, or establish authority to share the master provider account.

Endpoint: `GET /api/v1/integrations/loanhub/batlokoa/handshake`

## Deployment controls

By default `LOANHUB_BATLOKOA_HANDSHAKE_ENABLED=false`, so the endpoint returns 404. Never enable this before deploying a private dedicated shared secret to both services through the approved secret-management workflow; it must be at least 32 characters and must **not** reuse the platform JWT or M-PESA keys.

`LOANHUB_BATLOKOA_HANDSHAKE_SECRET` is configuration-only, with no generated or committed value. Leave disabled until secure provision and the LoanHub client are implemented and tested. A working Redis connection is mandatory for atomic nonce replay rejection; a Redis outage rejects the request.

## Signed request

The trusted LoanHub server must send:
- `X-LoanHub-Company-Id`: exact company UUID `4236a21f-5164-48aa-90f3-a35eccd23ae2`
- `X-LoanHub-Timestamp`: current Unix seconds
- `X-LoanHub-Nonce`: fresh cryptographically random URL-safe string, 24-128 characters
- `X-LoanHub-Signature`: lowercase hex HMAC-SHA256

Canonical bytes are UTF-8:
```text
timestamp + "\\n" + nonce + "\\n" + "GET" + "\\n" +
"/api/v1/integrations/loanhub/batlokoa/handshake" + "\\n" + company_id
```

The server rejects stale timestamps outside ±120 seconds, invalid company IDs, malformed signatures, replayed nonces, unavailable Redis, missing/short secrets and disabled feature flags. Only HTTPS should be used between services.

If validation passes, IthutePay checks its DB records: active sole master merchant, production M-PESA configuration 38542, inactive test Batlokoa application, zero API keys and shared custody disabled. Only a non-sensitive binding status is returned. This is **not** proof of a working LoanHub client or authorization for financial routing.

## Next integration work

Implement the LoanHub client with a short-lived signed GET, no client-browser secrets, explicit timeouts and strict TLS verification. Test on controlled staging, including cross-company impersonation, replay, timeout, and Redis-outage scenarios. Commercial zero fees and financial integration require separate approvals and tests.
