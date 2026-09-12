# Provider-first architecture

Ithute Pay Bridge is organized around a simple operating rule: **a user works with one payment provider at a time, while platform administration remains shared**.

## Frontend

The provider workspace catalogue lives in `apps/frontend/lib/provider-workspaces.ts`.

After sign-in the user lands on `/dashboard`, chooses a provider, and enters `/dashboard/provider`. The chosen provider is kept in UI state and browser storage only for the active workspace. Returning to the provider landing screen clears the selection so the user makes an explicit choice again.

The sidebar has two levels:

1. **Provider workspace** — only services relevant to M-Pesa, EcoCash, FNB or PayPal.
2. **Platform administration** — merchants, routing, API applications, provider setup, accounting, fees, settlements, operations, webhooks, audit, documentation and settings.

Provider-aware operational tables use `ProviderScopeBar` and `useProviderScopedRows` so records from different rails are not mixed together while a provider is active.

Every dashboard screen receives contextual guidance through `page-guides.ts` and the shared `PageHeader`. Shared `DataTable` controls use progressive disclosure: search remains visible, while advanced filters stay hidden until requested.

## Backend

Provider-specific construction now lives under:

```text
apps/backend/providers/
├── mpesa/
│   ├── factory.py
│   └── routes.py
├── ecocash/
│   ├── factory.py
│   └── routes.py
├── fnb/
│   ├── factory.py
│   └── routes.py
└── paypal/
    └── routes.py
```

`integrations/` remains responsible for low-level provider transport/client implementations. `providers/<provider>/` owns provider-specific interpretation of configuration, runtime construction, capability boundaries and provider-specific API composition.

`integrations/registry.py` is intentionally small. It selects application/gateway/simulator scope and delegates client construction to the appropriate provider package.

## Rule for new provider work

When adding a provider or provider-specific feature:

1. Put low-level HTTP/signing protocol code in `integrations/<provider>/`.
2. Put provider configuration interpretation, factories, provider services and provider-only routers in `providers/<provider>/`.
3. Keep generic payment resource orchestration in shared `services/` and `routers/` only when the behavior is genuinely provider-independent.
4. Add the provider and its supported workspace services to the frontend provider catalogue.
5. Add a page guide for every new operator-facing route.
6. Do not expose a provider service in navigation until the backend capability is implemented or deliberately marked as setup/roadmap.

This separation keeps the UI understandable and prevents provider-specific contracts from leaking into shared gateway code.
