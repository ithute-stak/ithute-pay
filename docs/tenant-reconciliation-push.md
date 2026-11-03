# Tenant reconciliation push delivery (Phase 17)

This component is **opt-in and OFF by default**. The existing direct M-PESA
provider, optional Golink adapter, balances, settlements and payment routes are
not involved.

## Activation prerequisites

1. Review and apply the additive Alembic migrations through
   `0013_tenant_recon_push` on the target database **before** deploying code
   that reads the new outbox table.
2. Confirm tenant memberships, central !thute Auth subject mappings and
   supported devices for the selected recipients.
3. Confirm Ithute Push service authentication and its available idempotency
   behavior with a non-production test.
4. Have each tenant owner/manager save their reconciliation alert policy through
   the business portal. Tenants without a saved policy never produce push jobs.
5. Configure the backend/worker environment:
   ```env
   ITHUTE_PUSH_ENABLED=true
   ITHUTE_PUSH_SERVICE_CLIENT_SECRET=<provision securely>
   ITHUTE_RECON_PUSH_DISPATCH_ENABLED=true
   ITHUTE_RECON_PUSH_BATCH_SIZE=50
   ```
6. Schedule a **separate container/process** to execute one bounded batch per
   invocation, e.g. a controlled scheduler task running
   `python -m services.tenant_recon_push_worker` with the backend package
   directory on `PYTHONPATH`. The web API does not run it automatically.

Do not commit or echo service secrets. Deploy a **single worker** first and
validate the delivery receipts. Database row leasing uses PostgreSQL
`FOR UPDATE SKIP LOCKED`, allowing safe scale-out later; test under worker
concurrency before scaling.

## Dispatch rules

- **Overdue:** sends to the active, !thute Auth-linked assigned investigator.
- **Unassigned:** sends to active, linked owner/manager members of that tenant.
- **Escalated:** sends to active, linked owner/manager members.
- Closed cases, suspended merchants, unapproved tenants, invalid recipients,
  acknowledged alerts and disabled alert types are excluded.
- One permanent outbox row per tenant, investigation case, alert type and
  recipient prevents repeated notifications on every scheduler run.
- Leases expire after 120 seconds; up to five attempts with exponential
  retry delays. Stable idempotency keys are supplied to !thute Push.
  The provider **must** honor these keys to prevent duplicate deliveries after
  failures that occur between send acceptance and local database commit.
- Only generic case references are sent; no phone numbers, payment amounts,
  customer details, provider credentials or evidence notes.
- Errors store a bounded code, not response payloads or secret-bearing logs.

## Visibility and rollout

The business portal shows the logged-in user's own delivery counts and whether
the worker is configured. It cannot start the worker or turn on push delivery.

Check a staged run with alerts for overdue, unassigned and escalated cases.
Verify statuses `delivered`, `pending`, `failed`, `cancelled`; verify closed
case cancellation, tenant separation, and acknowledgement suppression. Never
infer delivery solely from `enqueued`.

To immediately stop sends, set `ITHUTE_RECON_PUSH_DISPATCH_ENABLED=false` on
the worker service and stop its scheduler. Existing pending outbox records are
retained for audit and potential future re-enablement.
