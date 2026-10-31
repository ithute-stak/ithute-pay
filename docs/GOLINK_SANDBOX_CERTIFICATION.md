# Golink Transact sandbox certification gate

Golink must remain **disabled for live routing** until the actual provider behavior is verified and separately approved. Existing direct M-PESA, EcoCash and PayPal integrations are unaffected.

## 1. Obtain credentials and a previously created sandbox payment

Ask Golink for a sandbox merchant key (`glk_test_...`), webhook signing secret and a sample real sandbox payment ID with its original idempotency key, amount in minor units and rail (MPESA or ECOCASH). Never commit credentials, phone numbers, actual raw webhook bodies or a real customer identity.

## 2. Run a read-only verification

From `apps/backend`, set the environment variables `GOLINK_API_KEY`, `GOLINK_SANDBOX_PAYMENT_ID`, `GOLINK_EXPECTED_KEY`, `GOLINK_EXPECTED_AMOUNT_MINOR`, and `GOLINK_EXPECTED_RAIL`. Then run:

```sh
python -m scripts.golink_sandbox_probe
```

The probe performs **only** `GET /payments/{id}` against `https://sandbox.transact.golink.co.ls/api`. It verifies the returned ID, key, amountMinor, currency, direction, rail and status against the original record. It does not create payments, post funds, invoke ledger transitions, or output response bodies.

## 3. Verify the webhook contract using controlled provider fixtures

Capture only redacted documentation of Golink's webhook event type, payment ID field, signature header, signing algorithm and retry semantics. Confirm that the exact raw body is signed using `X-Golink-Signature: sha256=...` and that the event shape uses `data.id`. If not, update the adapter and regression suite before activation. Verify duplicate and reordered notifications in the provider sandbox.

## 4. Final go/no-go

Require all of: successful regression CI, passing PostgreSQL concurrency CI, successful read-only GET probe, verified webhook format, sandbox DEBIT initiation/confirmation with test accounts, verified reconciliation and ledger/settlement review, operational key rotation/rollback and explicit owner authorization. The current repo has not completed these live-provider checks. Never enable `GOLINK_COLLECTIONS_ENABLED` or `GOLINK_RECONCILIATION_ENABLED` by default, and never remove the existing direct-provider adapters.
