# Ithute Pay Bridge validation report

Validation performed on the improved gateway source on 2026-07-26.

## Passed

- Python compile for the FastAPI backend source.
- Backend automated test suite: **18 passed**.
- Alembic clean migration test against SQLite: `0001_initial -> 0002_accounting_auth -> 0003_gateway_middleman (head)`.
- FastAPI application import and regenerated route inventory.
- TypeScript strict typecheck for the Next.js frontend using the dependency set bundled with the supplied project.
- Next.js **16.2.4** optimized production build completed successfully, including the new `/dashboard/providers`, `/dashboard/routing`, `/dashboard/fees`, `/dashboard/settlements`, and `/payment/return` routes.
- Routed collection regression: gross collection -> configured fee -> net merchant payable -> M-Pesa settlement, with no duplicate collection for a repeated idempotency key.
- Provider callback/result audit deduplication regression.

## Live production boundary

The gateway now contains the application-side controls required to switch M-Pesa environments and operate the middleman settlement model. Real-money activation still requires the correct Vodacom Lesotho production application key, platform public key, registered Origin, gateway shortcode, HTTPS callback/result/timeout configuration and Vodacom approval/certification.

Do not commit production API keys to `.env`, source control, Next.js, mobile apps or client systems. Enter live credentials through the authenticated server-side provider configuration flow or a deployment secret process.
