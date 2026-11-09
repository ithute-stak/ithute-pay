# Phase 14 — Durable non-deliverable pass-through notification drafts

This increment persists one internal investigation notice draft per exception
case / approved platform-admin recipient / template version. The operator's
identity and the recipient's active platform-admin role are verified from
IthutePay's own User table. The recipient is an **internal user ID**, not a
phone number, email address, merchant/customer destination or delivery token.

## Safety and idempotency

- One draft per case, recipient, template and version; enforced with a
  database unique constraint and case row locking.
- Draft status is strictly `prepared` or `cancelled`; no `sent`, `queued`,
  `leased`, `delivered` or auto-retry states exist.
- Only a SHA-256 digest of the approved generic, non-success-claiming body
  is stored; there is no customer PII or provider credential.
- A duplicate preparation with identical template returns the original
  record without a new audit event. Cancellation is idempotent.
- Preparing and cancelling produce platform AuditLog entries in the caller's
  same database transaction.
- Drafts are tenant/application scoped and cannot be prepared for closed
  investigations. The service has no provider, SMS, push or email calls.
- Original M-Pesa and Golink integrations remain unchanged.

Alembic revision `0019_mpesa_pt_notice_drafts` creates the passive
notification table after revision `0018_mpesa_pt_exception_cases`.
The migration refuses to drop a populated table on downgrade.

## Future activation work

A **separate** opt-in recipient consent workflow, delivery-address
verification, template/content approval, tenant authorization, idempotent
provider delivery worker, privacy retention/deletion, rate limits and
reconciliation of delivery receipts must be designed and tested before
even internal SMS notifications are enabled. Prepared drafts are never
assumed delivered. Real-money M-Pesa pass-through execution remains
disabled pending provider certification, financial settlement and
regulatory approval. No production deployment or migration has been
performed by merging this code.
