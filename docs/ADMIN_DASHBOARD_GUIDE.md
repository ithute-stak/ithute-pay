# Ithute Pay Bridge — Administrator Dashboard Guide

The administrator dashboard is the operational control plane for the gateway. It is separate from merchant API-key authentication used by consumer systems.

## Sidebar and responsive navigation

On desktop, use the circular chevron on the sidebar edge to collapse or expand navigation. The live state is stored in Redux and the preference is persisted in browser local storage. The compact mode keeps icons and active-route highlighting while giving more horizontal space to dense accounting/transaction tables.

On smaller screens, navigation remains a full mobile drawer rather than forcing the compact desktop sidebar into a narrow viewport.

## Dashboard areas

### Overview
Realtime gateway indicators and high-level operational data. WebSocket activity invalidates relevant RTK Query cache tags so the console refreshes after money-movement events.

### Collections
Payment intents for customer-to-business payments. Review amount, merchant/application context, status and failure information.

### Payouts
Business-to-customer disbursements and provider results.

### Transactions
Provider-level movements and refresh/reversal visibility.

### Business transfers
B2B provider transfers.

### Authorizations
Two-stage authorize/commit/release operations.

### Direct debit
Mandates, their lifecycle and recurring charges.

### Accounting
Trial balance, journals, merchant payable visibility and settlement-related accounting. Accounting history should be compensated rather than deleted when a transaction is reversed.

### Reconciliation
Provider/gateway matching used to identify missing, duplicated or mismatched movements.

### Merchants
Tenant/business identities consuming the gateway.

### Applications & keys
Create a separate application for each environment/integration boundary. Use `test` first, then create a separate `live` application after UAT. Copy a newly generated API secret immediately because only its hash is retained.

### Providers
Configure provider adapters per merchant/application. Provider credentials remain backend-only and are encrypted before storage.

### Checkout & links
Hosted checkout sessions and shareable payment links.

### Webhooks & events
Inspect generated events, endpoints and delivery outcomes. Consumers should use signed webhooks for durable asynchronous state changes.

### Sandbox test lab
Run one supported product/scenario or the complete success suite. This lab uses an isolated system-managed test application forced to simulator mode.

### Documentation
Three dashboard tabs provide:

- administrator/deployment instructions;
- consumer integration instructions;
- sandbox testing instructions.

The repository `docs/` directory contains the expanded runbooks.

### Audit trail
Review privileged administrative activity and sandbox test executions.

### Settings
Runtime/security reference plus direct links to documentation and testing tools.

## Recommended merchant onboarding workflow

1. Create merchant.
2. Create `test` application.
3. Configure sandbox/simulator provider.
4. Run the built-in full success suite.
5. Create the merchant test API key.
6. Deliver test credentials through a secure channel.
7. Create webhook endpoint/signing secret as required.
8. Complete consumer UAT.
9. Review accounting and reconciliation.
10. Create a separate `live` application.
11. Configure approved live provider credentials.
12. Generate/deliver live API key securely.
13. Perform controlled live transaction and monitor webhook/accounting/reconciliation.

## Daily administrator checks

- gateway health/realtime connection
- failed or processing transactions
- payout failures
- webhook retries/failures
- unmatched reconciliation items
- accounting/trial-balance anomalies
- pending settlement requests
- provider configuration state
- audit entries for sensitive administrative actions

## Security practices

- give users the least privileged platform role required;
- do not share dashboard accounts;
- rotate credentials after suspected exposure;
- do not put provider/API secrets in screenshots or support messages;
- use HTTPS and secure cookies in production;
- treat audit/accounting records as historical evidence rather than editable operational data.
