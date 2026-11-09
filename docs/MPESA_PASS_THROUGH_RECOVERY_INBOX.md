# Phase 11 — Read-only reconciliation recovery inbox

This module inventories **stale, unresolved** M-Pesa pass-through
funding, beneficiary payout and refund intentions. It does not send any
transfer, run a worker, send notifications, modify accounting or mark
operations complete.

The report is strictly scoped to the caller's already-authenticated
merchant and application. Older `reserved` or `needs_reconciliation`
operations are identified by the existing original provider reference.

## Recovery classification

| Condition | Safe recommendation |
|---|---|
| Operation closed | Do not include in unresolved inbox |
| Operation recently reserved | Leave until the configured age threshold |
| Stale, sender/beneficiary not bound | Manual review |
| Stale, sender/beneficiary bound | Read-only query using the original reference |

Nothing in the inbox constitutes authority to submit or resubmit a
payment. Any authenticated provider result must pass Phase 7–9
verification and be reconciled atomically through the approved internal
service before settlement accounting changes.

## Deployment and authorization

The Phase 11 code is an **internal Python module only** with no public
endpoint or background scheduler. Operators cannot access it through a
new API route, and no production job is activated by merging.

All existing direct M-Pesa and Golink paths remain unchanged. Before
using this operationally, implement access-controlled operator review,
audit logging, credentials-scoped provider query, raw evidence retention,
financial reconciliation, and alerting. Production safety also depends on
the uncompleted provider and regulatory approvals for XXXX intermediary
movements.

The reported `created_at` is the outbox reservation timestamp; aging
is informational and never authorizes automatic movement.
