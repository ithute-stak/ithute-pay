# Ithute Pay Bridge — Sandbox Functional Testing Guide

Ithute Pay Bridge has two different test paths. They must not be treated as the same thing.

## 1. Local simulator

The local simulator is deterministic and sends no traffic to M-Pesa. It exists to test Ithute Pay Bridge business flows, accounting, idempotency, checkout, settlement, reconciliation and error handling without depending on a provider account.

The administrator lab creates/reuses an internal workspace:

```text
Merchant     Ithute Pay Bridge Sandbox Lab
Application  Ithute Pay Bridge Sandbox Test Lab
Environment  test
Provider     mpesa
Mode         simulator
```

The local simulator can exercise every gateway flow implemented by PayBridge, even when the corresponding M-Pesa product has not been enabled for a real M-Pesa application.

Deterministic local simulator scenarios:

```text
26658000001 -> success
26658000002 -> insufficient funds
26658000003 -> processing / unknown
```

The lab is available only to platform administrator roles and can be disabled with:

```env
SANDBOX_TEST_LAB_ENABLED=false
```

## 2. Real M-Pesa OpenAPI sandbox

The real M-Pesa sandbox sends network requests to the configured M-Pesa OpenAPI sandbox environment. It requires an active M-Pesa provider environment in `sandbox` + `live` mode with:

- the Service Provider Code associated with the M-Pesa application/product;
- the Origin registered for that application;
- the application API key;
- the M-Pesa public key;
- at least one M-Pesa product capability enabled in Providers.

### Ithute known-good sandbox compatibility profile

A previously working Ithute implementation was recovered and compared directly with the current gateway. Its Vodacom Lesotho sandbox wire profile was:

```text
Base URL                  https://openapi.m-pesa.com
Environment               sandbox
Market                    vodacomLES
Country                   LES
Currency                  LSL
Service Provider Code     000000
Origin                    *
Session activation wait   30 seconds
HTTP request timeout      60 seconds
```

For C2B single-stage payments that implementation did **not** send `input_APIVersion`; PayBridge now matches that C2B payload shape.

This profile is a project compatibility preset because it is known to have worked for Ithute. It is **not** treated as a universal M-Pesa rule and must never be copied automatically into Production. If the M-Pesa portal assigns a different Sandbox Service Provider Code or Origin to the application, the portal/application values take precedence.

Production activation explicitly rejects the sandbox compatibility shortcode `000000` and Origin `*` so those values cannot accidentally be promoted into a live organisation environment.

Secrets are write-only in the Providers console. When editing an existing configuration, leaving API-key/public-key fields blank preserves the already stored values.

## M-Pesa product capabilities

M-Pesa applications are product-scoped. In Providers, select only the products that have been selected/approved for the M-Pesa application/environment:

- C2B collection
- reversal / refund
- transaction status query
- B2C payout
- B2B transfer
- two-stage C2B
- direct debit

PayBridge keeps C2B collection, reversal and query enabled as a backward-compatible baseline for its existing online-payment integration. B2C, B2B, two-stage payment and direct debit are disabled by default and must be explicitly enabled for the provider environment before live calls are allowed.

The Test Lab automatically hides/blocks live-sandbox products that are not enabled. This prevents an implemented PayBridge adapter from being mistaken for an enabled M-Pesa application product.

## Product coverage in the local simulator

### 1. Collections
Creates and confirms a C2B payment intent, then checks the resulting status.

### 2. Payouts
Creates a business-to-customer payout and validates provider outcome mapping.

### 3. Business transfers
Runs a B2B transfer to a simulator receiver party code.

### 4. Two-stage authorization
Creates an authorization and, on success, commits it.

### 5. Direct debit
Creates a mandate and mandate charge.

### 6. Hosted checkout
Creates a checkout session and executes its public-token payment flow.

### 7. Payment links
Creates a reusable payment link and executes its public payment flow.

### 8. Reversal
Creates a successful collection, finds the provider transaction and reverses it.

### 9. Settlement request
Creates inbound value and then requests settlement within available balance.

### 10. Accounting integrity
Checks that debit and credit totals remain equal and non-zero.

### 11. Reconciliation
Creates a provider transaction and records a matched reconciliation item.

### 12. Webhook signing
Generates and independently verifies the production-format `X-IPB-Signature`.

## Real M-Pesa C2B sandbox flow

For a live C2B test, PayBridge:

1. obtains a SessionKey from the M-Pesa sandbox using the configured API key, public key and Origin;
2. observes the configured SessionKey activation delay;
3. calls the C2B single-stage endpoint with the configured market, country, currency and Service Provider Code;
4. records the provider response, conversation identifiers and transaction identifiers;
5. posts gateway accounting according to the resulting provider status;
6. exposes provider proof in the Sandbox Test Lab result.

The deterministic M-Pesa sandbox MSISDN values used by the live Test Lab are preserved exactly and are not normalized into Lesotho customer phone numbers.

## Provider errors

Provider errors are returned as provider results rather than converted into simulated success.

For example, if M-Pesa returns `INS-13 / Invalid Shortcode Used`, PayBridge marks the test failed and adds configuration guidance telling the operator to verify the exact Service Provider Code attached to the active M-Pesa application/product. If the rejected Sandbox value is `0000`, the guidance also points out that the recovered working Ithute profile used `000000`.

Transport uncertainty or provider timeouts must not be retried as a brand-new payment. They are handled as uncertain state and recovered through transaction-status/reconciliation logic.

## Admin testing API

```http
GET  /api/v1/admin/testing/catalog
POST /api/v1/admin/testing/run
POST /api/v1/admin/testing/run-all
GET  /api/v1/admin/testing/history
```

All routes require a platform administrator session. `run-all` remains a local-simulator suite. Live M-Pesa tests are run product-by-product and only for products enabled on the active provider environment.

## Audit trail

Single runs write `sandbox_test.executed`; complete local suites write `sandbox_test.suite_executed`. The dashboard combines recent Redux session results with persisted audit history.

## Production

The Sandbox Test Lab refuses production M-Pesa configurations. Production credentials, Origin, organisation shortcode and enabled products must be configured separately and should only be activated after M-Pesa/Vodacom onboarding, organisation testing and approval are complete.

Before production, ensure externally reachable callback/result/timeout URLs use the deployed HTTPS domain rather than `localhost`.

## Recommended test order before a release

1. Run backend automated tests and frontend lint/typecheck/build.
2. Deploy the candidate image to sandbox/UAT.
3. Run the local simulator success suite.
4. Run simulator failure/processing scenarios.
5. Confirm accounting and reconciliation remain correct.
6. Configure the real M-Pesa sandbox with the application values. For the recovered Ithute sandbox profile, start with `000000` and `Origin: *`, then use different values only when the M-Pesa application explicitly provides them.
7. Test the M-Pesa SessionKey connection.
8. Run each enabled real-sandbox product and inspect provider proof.
9. Complete organisation UAT, including payments, refunds, reconciliation and transaction inquiries.
10. Only then promote an approved production environment.
