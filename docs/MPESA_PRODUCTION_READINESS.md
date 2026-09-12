# M-Pesa OpenAPI production readiness

This checklist is based on the M-Pesa OpenAPI portal documentation reviewed for Ithute Pay Bridge on 2026-08-18. It is intended to keep the provider adapter aligned with the documented wire contract while avoiding unsafe retry or callback behaviour around real money.

## Vodacom Lesotho identity

For Vodacom Lesotho use:

- Market: `vodacomLES`
- Country: `LES`
- Currency: `LSL`
- Sandbox base path: `https://openapi.m-pesa.com/sandbox/ipg/v2/vodacomLES/`
- Production/OpenAPI base path: `https://openapi.m-pesa.com/openapi/ipg/v2/vodacomLES/`

PayBridge now validates this market/country/currency identity immediately before a provider request. An environment typo is rejected instead of silently falling through to the production path.

## SessionKey contract

1. Encrypt the application API key with the platform public key using RSA PKCS#1 v1.5.
2. Base64-encode the encrypted bytes.
3. Call `GET getSession/` with:
   - `Content-Type: application/json`
   - `Authorization: Bearer <encrypted API key>`
   - `Origin: <registered origin>`
4. Accept only HTTP 200 with `output_ResponseCode=INS-0` and a non-empty `output_SessionID`.
5. Allow the configured activation delay before using a new SessionKey.
6. Encrypt the SessionKey with the same platform public-key mechanism for subsequent API calls.

The portal material reviewed for this project showed different public-key material between environments. Keep sandbox and production application credentials/public keys separate. Do not copy a sandbox public key or API key into production.

## Supported Lesotho API coverage

| Product | Method | Provider path | PayBridge operation |
|---|---|---|---|
| Generate SessionKey | GET | `getSession/` | `get_session_key()` |
| C2B Single Stage | POST | `c2bPayment/singleStage/` | `collect()` |
| B2C Single Stage | POST | `b2cPayment/` | `payout()` |
| B2B Single Stage | POST | `b2bPayment/` | `transfer()` |
| Reversal | PUT | `reversal/` | `reverse()` |
| Query Transaction Status | GET | `queryTransactionStatus/` | `query()` |
| C2B Multi Stage | POST | `c2bPayment/multiStage/` | `authorize_collection()` |
| Update Transaction Status | PUT | `updateTransactionStatus/` | `update_authorization()` |
| Direct Debit Create | POST | `directDebitCreation/` | `create_mandate()` |
| Direct Debit Payment | POST | `directDebitPayment/` | `charge_mandate()` |
| Query Direct Debit | GET | `queryDirectDebit/` | `query_mandate()` |
| Cancel Direct Debit | PUT | `directDebitCancel/` | `cancel_mandate()` |

`Query Beneficiary Name` was not listed for Vodacom Lesotho in the reviewed portal material, so PayBridge does not expose it as a Lesotho capability.

## Financial retry policy

Never treat HTTP status alone as proof that a financial request was not processed.

The M-Pesa product documentation explicitly uses:

- HTTP 401 / `INS-6` = Transaction Failed
- HTTP 408 / `INS-9` = Request timeout
- HTTP 409 / `INS-10` = Duplicate Transaction

Therefore:

- `401 + INS-6` is a business failure and MUST NOT be replayed automatically.
- `408 / INS-9` and `409 / INS-10` are uncertainty states and should be reconciled with Query Transaction Status.
- A SessionKey refresh/retry is allowed once only when the provider response explicitly identifies the SessionKey as expired or invalid. A generic HTTP 401 is not enough.
- Reuse the same provider request identity when a proven authentication-level retry is made.

## Provider-boundary validation

Before a network request, PayBridge validates:

- environment is sandbox or production/openapi
- market/country/currency identity is consistent
- request currency matches the configured provider currency
- provider/party codes are 4-12 alphanumeric characters
- ThirdPartyConversationID is within the documented 40-character contract
- transaction references stay within the documented limits
- descriptions are non-empty, provider-safe and at most 256 characters
- monetary amounts are valid and positive where required
- MSISDN values are digits only
- direct-debit mandate IDs and references have valid shapes
- Multi Stage and Update Transaction Status use API version `3.1`
- commit/uncommit operation is `1` or `0`

The generic portal documents an MSISDN length of 12-14 digits. A normal international Lesotho mobile number (`266` plus an 8-digit national number) is 11 digits, while provider sandbox fixtures are 12 digits. PayBridge therefore accepts 11-14 numeric digits pending an explicit Vodacom Lesotho production confirmation. Do not tighten this to 12-14 without a verified Lesotho provider result.

## Description handling

M-Pesa documents restricted purchased/payment item descriptions, and the Vodacom Lesotho sandbox has returned `INS-30` for punctuation in descriptions. PayBridge normalizes only the provider-bound description to letters, numbers and spaces. The original merchant description remains unchanged in PayBridge storage.

## Direct Debit rules

Provider frequency values:

- `01` Once off
- `02` Daily
- `03` Weekly
- `04` Monthly
- `05` Quarterly
- `06` Half Yearly
- `07` Yearly
- `08` On Demand

Rules enforced by PayBridge:

- When Frequency is absent, FirstPaymentDate and payment-day ranges must be absent.
- When Frequency is Once/Daily/Weekly/On Demand, FirstPaymentDate is required by the provider flow and payment-day ranges are not allowed.
- Monthly/Quarterly/Half Yearly/Yearly may use payment-day ranges.
- Start day cannot exceed end day.
- The service supplies the current date when a persisted mandate has a frequency but no FirstPaymentDate.

Direct Debit Create, Query and Cancel synchronous successes may not contain `output_TransactionID`. PayBridge treats provider-specific terminal fields such as MandateID, MandateStatus, TransactionReference or MsisdnToken as synchronous completion evidence. A generic async acceptance with only conversation identifiers remains `processing`.

## C2B Multi Stage

C2B Multi Stage reserves/authorizes funds first. It must be completed with Update Transaction Status:

- commit = `input_CustomerMSISDN: "1"`
- uncommit/release = `input_CustomerMSISDN: "0"`
- `input_APIVersion: "3.1"`
- the provider TransactionID and customer voucher code are required for stage two

Do not leave reservations indefinitely. If stage one is accepted but stage two has not completed, surface that state operationally until commit/release is resolved.

## Async callback contract

M-Pesa async results use the provider's OriginalConversationID and the PayBridge ThirdPartyConversationID to correlate the result. PayBridge:

- deduplicates callback bodies by SHA-256
- limits M-Pesa callback matching to records whose provider is `mpesa`
- matches the high-entropy ThirdPartyConversationID
- when both values exist, verifies `input_OriginalConversationID` against the stored provider ConversationID before financial state can change
- records correlation mismatches in the callback audit table and acknowledges the provider packet without applying money movement
- returns the documented acknowledgement fields:
  - `output_OriginalConversationID`
  - `output_ResponseCode: "0"`
  - `output_ResponseDesc: "Successfully Accepted Result"`
  - `output_ThirdPartyConversationID`

The reviewed M-Pesa callback documentation does not define an `X-Provider-Callback-Token` header. `PROVIDER_CALLBACK_TOKEN` is therefore optional and should be enabled only when Vodacom supports the header or a trusted reverse proxy injects it. Otherwise protect the callback route with provider-supported network controls/reverse-proxy policy and the built-in correlation checks.

## Sandbox before production

Before production activation:

1. Configure a dedicated M-Pesa sandbox application with its own API key and platform public key.
2. Select only the products approved for that application.
3. Confirm `vodacomLES`, `LES`, `LSL`, sandbox service provider code and registered Origin.
4. Run SessionKey generation successfully.
5. Use the provider sandbox fixture numbers from the Test Lab.
6. Run C2B Single Stage and confirm synchronous or async completion.
7. Verify Query Transaction Status on an uncertain transaction.
8. Verify B2C, B2B and Reversal only if those products are enabled for the M-Pesa application.
9. Verify C2B Multi Stage plus commit and release paths.
10. Verify Direct Debit Create, Query, Payment and Cancel if Direct Debit is enabled.
11. Verify a real provider callback reaches the public HTTPS result URL and is acknowledged.
12. Confirm duplicate callbacks do not double-book a transaction.
13. Confirm a callback with a mismatched OriginalConversationID cannot mutate financial state.
14. Record a clean provider response for `INS-0`, `INS-6`, `INS-9`, `INS-10`, insufficient balance and invalid input cases.

## Production activation

Production should not be activated until all of the following are true:

- production application is approved in the M-Pesa portal
- production API key is stored encrypted
- production platform public key is configured from the production application/portal material
- production shortcode is confirmed by Vodacom
- Origin exactly matches the value registered with the application
- callback/result/timeout URLs are public HTTPS endpoints
- application capabilities match the products actually enabled by M-Pesa
- sandbox credentials are absent from production configuration
- `PROVIDER_CALLBACK_TOKEN` is blank unless a supported upstream mechanism supplies it
- reconciliation worker is running
- database backups and ledger monitoring are enabled
- operator has tested a low-value live transaction and its callback/query result before normal traffic is opened

## Testing policy

CI tests use simulators/mocks and must never contain live M-Pesa secrets. Real network verification belongs in the credential-gated Admin Sandbox Test Lab or a controlled operator test. Passing mocked CI proves PayBridge's contract handling; it does not by itself prove that a specific M-Pesa application, shortcode, Origin, product entitlement or public key is accepted by Vodacom.
