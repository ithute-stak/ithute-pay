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


## Phase 18 — delivery monitoring and controlled retries

The portal now provides recipient-scoped delivery monitoring. Active tenant
owners and managers can inspect delivery statuses for their business, while
other members can inspect only their own delivery records. The API never
returns recipient Auth subjects, provider credentials or provider payloads.

The monitoring API is
`GET /api/v1/tenant-portal/merchants/{merchant_id}/reconciliation/alerts/deliveries`
with optional `status` and `limit` query parameters.

An active owner or manager may queue a **single** manual retry only after a
delivery has reached `failed` and exhausted all five automatic attempts:

`POST /api/v1/tenant-portal/merchants/{merchant_id}/reconciliation/alerts/deliveries/{delivery_id}/retry`

The retry requires the central push integration and reconciliation dispatcher
to be enabled; it is rejected for closed cases, unknown or foreign delivery
records, non-failed deliveries and records already manually retried. The retry
increments a separately constrained `manual_retries` counter and resets the
attempt counter only once. The worker then rechecks current recipient status,
tenant approval, alert policy, assignment, acknowledgement and case status
before delivery. The same provider idempotency key is reused.

Apply the new **`0014_tenant_push_manual_retries`** migration after 0013 and
**before** deploying the Phase 18 backend. Production sending remains OFF by
default. Manual retry requests merely queue work; they do not send a push from
the web request.

Operational caveat: a provider must honor idempotency keys to suppress
duplicates after an ambiguous network acknowledgement. Monitoring reports
local queued/accepted states and must not be interpreted as device delivery
receipts without independent provider confirmation.
