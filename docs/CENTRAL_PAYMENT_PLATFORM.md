# Ithute Pay — Central Payment Platform

Ithute Pay is the centralized payment system for Ithute Solutions products and for approved external/public projects that integrate with Ithute Pay.

It is not a LoanHub-specific bridge and no consuming project should need to own provider credentials or reimplement M-Pesa, EcoCash or other provider-specific payment logic when Ithute Pay already supports that capability. Consumer systems integrate with one Ithute Pay API and Ithute Pay owns the provider-facing payment lifecycle.

## Platform rule

```text
Ithute-owned projects ───────┐
                            │
External/public projects ───┼──> api.pay.ithute.co.ls ──> Ithute Pay
                            │                          ├─ provider routing
Partner/VCL test clients ───┘                          ├─ C2B / collections
                                                       ├─ B2C / payouts
                                                       ├─ B2B / transfers
                                                       ├─ reversals / queries
                                                       ├─ mandates / direct debit
                                                       ├─ webhooks / events
                                                       ├─ fees / settlement
                                                       └─ accounting / reconciliation
                                                                │
                                                                ├─ M-Pesa
                                                                ├─ EcoCash
                                                                ├─ PayPal
                                                                └─ future providers
```

## One payment core, many consumer projects

The existing `Merchant -> Application -> ApiKey` boundary is the canonical consumer model.

### Ithute-owned projects

Ithute Solutions is represented as a merchant/business boundary and each first-party product is represented by one or more applications. Examples include LoanHub, RSL POS, Mailbox DNS, Ithute Account and future Ithute products.

Each project receives its own test/live application, API keys, scopes, webhook endpoints, idempotency namespace and transaction records. An Ithute project does not bypass normal payment controls merely because it is first-party.

### External/public projects

An external organization is represented by its own merchant. Each of its systems/apps is an application under that merchant, with separate test/live credentials and webhook configuration.

External projects use the same payment API contract as Ithute products. Provider credentials stay inside Ithute Pay and are never copied into the consuming project.

### VCL / partner testing

`portal.pay.ithute.co.ls` is a consumer testing surface. It is not a platform-super-admin portal. It accepts test/sandbox application credentials only and exposes the payment capabilities a consumer needs to certify its integration.

## Public surfaces

- `https://pay.ithute.co.ls` — Ithute Pay management application.
- `https://api.pay.ithute.co.ls` — canonical payment API for Ithute and external projects.
- `https://portal.pay.ithute.co.ls` — partner/VCL sandbox testing portal.

The API remains the system of record. Consumer projects should not connect directly to the Ithute Pay PostgreSQL database and should never read another consumer's records.

## Authentication boundary

Human administrators use central `!thute Auth` for SSO into the Ithute Pay management application.

Machine-to-machine payment requests use application-scoped Ithute Pay API keys (`ipb_test_...` / `ipb_live_...`). The existing prefix is retained for backwards compatibility even though the product is now branded simply as **Ithute Pay**. Requests may additionally use HMAC request signing, scopes and `Idempotency-Key` according to the endpoint contract.

This separation is intentional: central Auth owns human identity; Ithute Pay owns payment-client authorization and payment permissions.

## Data and isolation

Every financial resource carries the consumer boundary through `merchant_id` and `application_id`. The central platform therefore supports consolidated operations while retaining per-consumer isolation.

The following remain centralized in Ithute Pay:

- provider credentials and provider configuration;
- provider routing and failover policy;
- collections/C2B;
- payouts/B2C;
- transfers/B2B;
- transaction status queries;
- reversals/refunds;
- mandates/direct debit;
- hosted checkout/payment links;
- webhook signing/delivery;
- fees, settlement and reconciliation;
- audit events and payment accounting.

Consumer-specific business data remains in the consumer project. LoanHub loans, POS sales, Mailbox subscriptions, school student records or an external merchant's domain objects are not moved into the Ithute Pay database. Consumer systems send stable references/metadata and reconcile the resulting Ithute Pay transaction IDs/statuses through API/webhooks.

## Integration rule for new projects

A new project should be onboarded by creating a merchant (or using the Ithute Solutions merchant for first-party products), creating a test application, issuing scoped test credentials, configuring a webhook, certifying the required flows in the portal, then creating a separate live application and live credentials after approval.

No new Ithute project should implement its own direct provider integration when the capability is already provided by Ithute Pay. Provider-specific behavior belongs in Ithute Pay so fixes, security controls, audit, settlement and reporting remain centralized.
