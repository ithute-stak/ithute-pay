# Provider regression gate: direct M-PESA + optional Golink

## Scope

The `IthutePay offline provider regression gate` CI workflow runs
PostgreSQL-backed tests with **synthetic** data, fake credentials and simulated
provider HTTP responses. It must not call a real M-PESA or Golink endpoint,
send money, change a merchant shortcode or enable production routing.

Checks include:

- The active provider registry retains the existing direct M-PESA factory,
  along with the original EcoCash and FNB providers. Golink must remain
  unregistered as an active payment provider.
- Golink client credentials must match sandbox/production mode, and
  production initiation remains certification-blocked.
- Golink sandbox HTTP GET reconciliation verifies the original payment ID,
  idempotency key, amount, currency, direction and rail. A mismatched provider
  record must fail closed.
- A network-unknown Golink response must not be counted as successful.
- M-PESA callback identity correlation and terminal response classification
  must retain their existing failure and idempotency semantics.
- Callback replay and concurrent terminal-posting tests execute against
  disposable PostgreSQL, not an SQLite concurrency substitute.

## Required external certification (not performed by CI)

Before activating any new Golink routing, retain **provider-issued sandbox
evidence** for:

1. Read-only GET on an existing transaction, matching all immutable fields.
2. Explicitly authorised sandbox collection initiation and status inquiry.
3. Signed callback delivery and duplicate/replayed callbacks.
4. Processing, success, failure and unknown-network-outcome reconciliation.
5. Real direct M-PESA sandbox parity and unchanged existing merchant routing.
6. Operator approval and independent review of fees, custody and settlement.

Do **not** accept offline CI as proof that the third-party sandbox, callback
origin, merchant keys or production certification are valid. Keep the
separately approved payment activation process and all existing direct M-PESA
integrations intact.
