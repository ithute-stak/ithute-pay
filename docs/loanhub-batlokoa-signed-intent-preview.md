# Batlokoa signed collection-intent preview (disabled by default)

This is **not a payment initiation API**. It performs read-only preview of a
collection using the existing inactive test application and master merchant.
It does not create a payment intent, reserve idempotency keys, post fees,
contact M-PESA, authorize custody, or move money.

## Feature gate

`LOANHUB_BATLOKOA_INTENT_PREVIEW_ENABLED=false` by default, independently
of `LOANHUB_BATLOKOA_HANDSHAKE_ENABLED`. Production rollout requires
separate operational approval. The existing signed GET handshake remains
unchanged.

## Request contract

`POST /api/v1/integrations/loanhub/batlokoa/collection-intent-preview`

JSON body:

```json
{
  "amount": "100.00",
  "currency": "LSL",
  "source_reference": "loan_ref_TEST1234567",
  "idempotency_key": "collect_req_TEST123456789"
}
```

`source_reference` and `idempotency_key` must be **opaque references**, not
borrower names, phone numbers, identity numbers, or other personal data.
Extra fields, including caller-supplied merchant/company IDs, are rejected.
Request body limit: 4096 bytes.

Four required headers:

- `X-LoanHub-Company-Id`: exact registered Batlokoa company ID.
- `X-LoanHub-Timestamp`: current Unix seconds, maximum 120 seconds skew.
- `X-LoanHub-Nonce`: fresh URL-safe token, 24 to 128 characters.
- `X-LoanHub-Signature`: lowercase/uppercase HMAC SHA-256 hex of canonical bytes.

Canonical signed message (UTF-8, LF separators):

```text
{timestamp}
{nonce}
POST
/api/v1/integrations/loanhub/batlokoa/collection-intent-preview
{company_id}
{sha256_hex_of_exact_request_body_bytes}
```

The dedicated read-only handshake secret is used as the HMAC key. The
request body is authenticated **byte-for-byte**: changing whitespace or field
order requires a new signature. The Redis nonce store is shared with the
handshake and atomic single-use. Replay-store unavailability fails closed.

## Responses

- `200`: deterministic preview/fingerprint and explicit
  `provider_execution_enabled=false`,
  `financial_posting_enabled=false`, `idempotency_reserved=false`.
- `401`: invalid signature, company, expired timestamp, or replay.
- `404`: separate feature flag disabled.
- `409`: database-verified master merchant, provider or inactive test
  application binding is not ready.
- `413`: excessive request size; `415`: unsupported content type;
  `422`: invalid body.
  
The API validates Batlokoa's company identity only through the signed
company claim and the server's verified records; it does **not** establish
ownership of a specific borrower or loan. Before any eventual payment
execution, LoanHub must separately authorize the borrower/loan relationship,
and IthutePay must implement durable, transactional idempotency,
provider authorization, fees, custody, settlement and reconciliation.

Do not enable the flag in production solely because the test suite passes.
