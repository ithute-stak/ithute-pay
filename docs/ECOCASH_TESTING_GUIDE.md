# EcoCash Instant Payment v1.0.0 — Sandbox Testing Guide

This guide is based on the authenticated EcoCash developer portal material supplied for the `EcoCash Instant Payment` product.

## Authentication

EcoCash Instant Payment uses HTTP Basic Authentication on every request.

- Request Sandbox Access in the EcoCash developer portal.
- The username is returned by the portal.
- The password is delivered to the developer inbox.
- Send `Authorization: Basic <Base64(username:password)>` on every API request.
- There is no token-exchange step for this product.
- Do not commit the username/password to source control.

The portal states a rate limit of 500 requests per minute.

## Sandbox API base

```text
https://developers.ecocash.co.zw/sandbox/payment/v1
```

The three documented core APIs are:

```text
POST /transactions/amount/
GET  /{endUserId}/transactions/amount/{clientCorrelator}
POST /transactions/refund/
```

`tranType` values documented by the portal are:

```text
MER = merchant charge
REF = refund
REV = reversal
```

IthutePayBridge uses `MER` for Charge Request and `REF` for the existing Refund flow. The supplied portal excerpt did not include the expanded Refund/Reversal request schema, so PayBridge does not guess a different `REV` payload.

## Merchant configuration

The portal's authenticated Authentication section and its Test Data section show different merchant-code / merchant-number examples. Therefore IthutePayBridge deliberately does not hard-code either pair.

Use the Merchant Code and Merchant Number shown for the developer account in the authenticated portal credential reference.

The non-secret standard sandbox request values shown in Test Data are:

```text
terminalID        UAT00003
countryCode       ZW
location          Harare
superMerchantName ECOCASH
merchantName      UAT STORE 3
channel           POS
```

The portal examples show merchant PIN `1234`, but PayBridge still stores the configured PIN as a secret rather than embedding it in source code.

## Charge Request

The documented endpoint is:

```text
POST /transactions/amount/
```

The request includes:

```text
clientCorrelator
notifyUrl
referenceCode
tranType = MER
endUserId
remarks
transactionOperationStatus = Charged
paymentAmount.charginginformation.amount
paymentAmount.charginginformation.currency
paymentAmount.charginginformation.description
paymentAmount.chargeMetaData.channel
merchantCode
merchantPin
merchantNumber
countryCode
terminalID
location
superMerchantName
merchantName
```

`clientCorrelator` must be unique per transaction and is used by Transaction Lookup.

## Test numbers

A live sandbox number must first be added and OTP-verified under EcoCash `Test Numbers`.

The supplied portal material documents these accepted forms:

```text
263XXXXXXXXX
07XXXXXXXX
```

The portal's API example also uses a local nine-digit form such as:

```text
773047653
```

IthutePayBridge preserves all of these documented Zimbabwe forms instead of applying Lesotho `266` normalization.

## Sandbox PIN scenarios

The subscriber enters the PIN on the EcoCash USSD prompt after the Charge Request arrives. The merchant API request does not contain the PIN.

| Scenario | Customer PIN | Expected message |
| --- | --- | --- |
| Successful transaction | `0000` | `Transaction Successful` |
| Insufficient funds | `1111` | `Insufficient Balance` |
| Incorrect PIN | `2222` | `Transaction Failed - Invalid PIN` |
| Limit exceeded | `9999` | `Transaction Limit Exceeded` |

The portal states that all four PIN scenarios can return HTTP 200; the outcome is indicated in the response body/status message.

## Transaction Lookup

The documented lookup path is:

```text
GET /{endUserId}/transactions/amount/{clientCorrelator}
```

IthutePayBridge therefore stores/reuses the original customer MSISDN and original `clientCorrelator` when refreshing an EcoCash transaction.

The Test Lab requires the original `clientCorrelator` for a manual Lookup run instead of silently generating a new one.

## Refund / Reversal

The core Refund/Reversal endpoint is:

```text
POST /transactions/refund/
```

For PayBridge's generic transaction reversal workflow, the original EcoCash transaction ID, original customer MSISDN, currency and original merchant reference are reconstructed from the source provider transaction before calling the EcoCash adapter.

The supplied portal material did not include the full expanded refund request schema, so fields beyond the existing verified adapter shape have not been invented.

## EcoCash callback / notifyUrl

Charge Request includes `notifyUrl`. IthutePayBridge uses:

```text
/api/v1/provider-callbacks/ecocash
```

A legacy configuration that accidentally inherited the M-Pesa callback path is repaired at runtime for EcoCash requests.

The supplied authenticated portal material did not include callback-signature or webhook-authentication requirements. Those should not be guessed; update the provider callback security only when the corresponding EcoCash documentation is available.

## Error reference

The supplied portal lists these developer-facing errors:

```text
E001 missing required field
E002 invalid MSISDN format
E003 invalid currency
E004 invalid amount
E005 duplicate correlator
E006 invalid credentials
E007 sandbox not enabled
E008 transaction not found
E009 refund not eligible
E010 insufficient funds
E011 barred MSISDN
E012 refund exceeds original
E013 limit exceeded
E014 internal server error
E015 service unavailable
```

The portal's Test Data also states that reusing a correlator returns the existing transaction, which differs from the Error Reference entry describing `E005 Duplicate correlator`. IthutePayBridge does not invent a reconciliation for that documentation difference; it preserves the provider response that is actually returned.

## Certification / production request

The portal requires the standard test script to be completed before applying for Production. The pre-populated certification cases include:

```text
TC-001 Charge Request / PIN 0000 / successful
TC-002 Charge Request / PIN 1111 / insufficient balance
TC-003 Charge Request / PIN 2222 / invalid PIN
TC-004 Charge Request / PIN 9999 / limit exceeded
TC-005 Transaction Lookup
TC-006 Refund / Reversal
```

Record the merchant reference, expected result, actual result, pass/fail status and comments for each test case, then attach the completed script to the Production access request.
