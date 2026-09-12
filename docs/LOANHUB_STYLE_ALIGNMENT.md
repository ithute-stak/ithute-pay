# LoanHub-style backend alignment

Ithute Pay Bridge remains a standalone payment gateway. This refactor copies the architectural and coding conventions of the supplied LoanHub backend without copying LoanHub lending behaviour.

## Backend layout

```text
apps/backend/
├── api/
│   └── v1/
│       └── router.py
├── core/
│   ├── access_control.py
│   ├── error_monitoring.py
│   ├── error_response.py
│   ├── rate_limit.py
│   ├── realtime_events.py
│   ├── security.py
│   └── websocket_manager.py
├── database/
│   ├── config/
│   │   └── config.py
│   ├── models/
│   │   ├── audit_log.py
│   │   ├── checkout.py
│   │   ├── enums.py
│   │   ├── finance.py
│   │   ├── idempotency.py
│   │   ├── mandate.py
│   │   ├── merchant.py
│   │   ├── payment.py
│   │   ├── provider.py
│   │   ├── user.py
│   │   └── webhook.py
│   ├── schemas/
│   ├── base.py
│   └── session.py
├── integrations/
│   └── mpesa/
├── routers/
├── services/
├── utils/
│   ├── authContextMiddleware.py
│   ├── convex.py
│   ├── decode_encode_token.py
│   ├── helpers.py
│   └── load_setting_keys.py
├── workers/
├── alembic/
└── main.py
```

## What changed

- Settings moved to `database/config/config.py` and support either `DATABASE_URL` or `DB_*` fields.
- SQLAlchemy engine/session moved to `database/session.py`.
- Payment-gateway models are separated by domain under `database/models/` instead of one large `entities.py` file.
- Pydantic contracts live under `database/schemas/`.
- Authentication follows the same separation used by LoanHub: token encoding/decoding in `utils`, password/current-user security in `core/security.py`, and role/API-key scope enforcement in `core/access_control.py`.
- Request identity is stored in context variables through `AuthContextMiddleware`.
- Route modules live in `routers/` and are assembled by `api/v1/router.py`.
- Business logic remains in `services/`; external provider adapters remain in `integrations/`.
- Alembic uses the `alembic/` directory convention.
- Redis-backed WebSocket fan-out was added for platform dashboard realtime events.

## What did not change

Ithute Pay Bridge is still responsible for payment processing only. It does not absorb LoanHub concepts such as loans, borrowers, interest allocation, loan schedules, branch accounting, or contracts.

Existing gateway contracts remain available, including payment intents, payouts, B2B transfers, reversals, mandates, checkout, payment links, provider callbacks, developer webhooks, finance endpoints, administration, and reconciliation.

The existing database table/column contract is intentionally preserved by the style refactor, so no new schema migration is required merely to adopt the new source layout.
