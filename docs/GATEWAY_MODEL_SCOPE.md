# Gateway model scope

Ithute Pay Bridge is payment infrastructure, not a lending application.

## Included domains

- platform users and authentication sessions
- merchants, applications and scoped API keys
- payment intents / collections
- payouts
- business-to-business transfers
- payment authorizations (two-stage collections)
- provider configurations and provider operations
- provider transactions and status reconciliation
- reversals
- direct-debit mandates and mandate charges
- hosted checkout and payment links
- webhook endpoints, events and delivery attempts
- idempotency records
- immutable audit log
- fee rules
- ledger accounts
- journals and journal lines
- settlement requests
- reconciliation items

## Intentionally excluded

The gateway contains no borrower, loan, loan product, loan application, origination,
repayment schedule, contract, lending marketplace, company-client, employee, branch,
or document-studio model.

External products such as LoanHub store those concepts themselves and use Ithute Pay
Bridge only for verified money movement, provider state, accounting and payment events.
