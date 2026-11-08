# M-Pesa pass-through implementation (non-posting first increment)

## Architectural decision

The tenant retains operating float in its own M-Pesa merchant wallet YYYY.
On a M1,000 payout, an approved pass-through flow would move M1,010 from
YYYY to the IthutePay merchant XXXX, then M1,000 from XXXX to the client.
The M10 platform fee is **earned only after confirmation** of the client leg.
Funds received for incomplete transactions remain a settlement obligation.

Incoming flow: collection into XXXX, followed by B2B settlement of the
confirmed net proceeds into YYYY after applicable fees.

This first repository increment includes **only deterministic non-posting
quotes** in `services/mpesa_pass_through_quotes.py`. It does not call M-Pesa,
change route registration, move money, run migrations, create ledger entries,
or send SMS. Default IthutePay incoming/outgoing percentages are 1% and can
be overridden by approved, versioned tenant commercial agreements.

## Existing boundaries

- Use existing `Merchant -> Application -> ApiKey` authorization.
- Use existing `MerchantCommercialAgreement` approval and tenant KYC gate.
- Keep `PlatformMerchantSettings.shared_custody_enabled=False` and existing
  `TenantProviderAccount.enabled=False` gates untouched.
- Preserve `integrations.mpesa`, `services.payments`, `services.fees`,
  existing direct provider integrations, Golink, and settlement accounting.
- Do not use the simple reference SQL in the prior offline bundle as an Alembic
  migration. Reconcile models and accounting with the production schema first.
- The returned provider cost is an *estimate*: 1% incoming / 0% outgoing by
  configurable defaults, not a universal Vodacom tariff.

## Next integration checklist

1. Reconcile tariff precedence with existing `services.fees` to avoid double
   charging. Snapshot the approved quote and agreement version on creation.
2. Verify tenant shortcode ownership and M-Pesa B2B/B2C permissions.
3. Add persistent transactional state, unique indexes, idempotency and an
   outbox using the repository's existing PostgreSQL/Alembic conventions.
4. Dispatch each leg through the existing provider-operations mechanism,
   never retrying unknown outcomes as fresh movements.
5. Book temporary settlement liabilities; recognize platform revenue only
   after final beneficiary settlement, with reversals/refund handling.
6. Reconcile independently confirmed provider transaction identifiers and
   balances, and send accurate SMS using the existing notification boundary.
7. Run comprehensive CI, security and staged sandbox tests, and obtain
   appropriate Vodacom/regulatory authorization before enabling live execution.

## Testing

From `apps/backend` run:

```sh
python -m pytest -q tests/test_mpesa_pass_through_quotes.py
```

This module is intentionally fail-closed and cannot execute live money
movements. It is **not** a complete merged production payment engine.
