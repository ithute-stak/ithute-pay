# Phase 13 — Authenticated Pass-Through Operations API

The new `/api/v1/admin/mpesa-pass-through` routes expose the Phase 11
recovery inbox and Phase 12 investigation cases to authenticated active
`platform_admin` or `platform_super_admin` accounts ONLY.

## Routes

- `GET /recovery`: tenant/application-scoped stale-operation review.
- `GET /cases`: scoped investigation listing, no raw evidence or secrets.
- `POST /cases`: open an auditable, idempotent case for a reserved intent.
- `POST /cases/{case_id}/review`: investigate/escalate/close according to
  existing Phase 12 transition and provider-finality rules.
- `GET /cases/{case_id}/notification-preview`: safe generic, non-sendable
  notification preview without recipient information.

The route layer derives the operator from a verified logged-in session.
Merchant and application IDs serve as *explicit query filters* for platform
administrators only. They are not evidence of tenant authorization, and these
routes must never be reused for merchant self-service without new RBAC.

## Important boundaries

- No live B2B/B2C transfer, provider query, refund, reconciliation mutation,
  notification delivery worker, SMS, or journal execution is added.
- Case closure remains blocked while the underlying outbox movement is unresolved.
- The notification preview always marks `safe_to_send: false` and
  `delivery_enabled: false`. It cannot be interpreted as a delivery receipt.
- Admin actions generate existing `AuditLog` entries and case events.
- The provider and regulatory approvals for an XXXX intermediary arrangement,
  certified provider queries, raw evidence retention, true notification
  delivery, and operational deployment remain unresolved.
- Existing direct M-Pesa and optional Golink integrations are untouched.

Future milestones: recipient-authorized and idempotent notification outbox;
alerting/assignment; provider-certified query and safe dispatcher; provider
fee/reversal accounting; test-staging and production approval.
