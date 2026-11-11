# Phase 18 — Recovery monitoring release gate

This document covers the **optional, non-financial** M-Pesa pass-through recovery monitor.
It does not approve live payouts, B2B/B2C transfers, refunds, reversals, merchant float movements,
customer notifications, or settlement.

## Implemented baseline

- Phase 16: read-only scoped recovery monitoring.
- Phase 17: persisted hourly snapshots, alert history, platform-admin acknowledgements and an **off by default** single-shot runner.
- Phase 18: offline configuration preflight (no connections or mutations).

## Operator steps — test/staging only

1. Ensure a documented database backup and restore drill exists. Record a restore-check artifact.
2. Verify the deployed Alembic revision is `0020_mpesa_pt_monitor_history` and inspect the target DB (the offline preflight cannot do this).
3. Run `PYTHONPATH=apps/backend python apps/backend/scripts/mpesa_pt_monitor_preflight.py` with the scheduler disabled. Its default passing result only means configuration is passive.
4. For an approved staging-only scheduled capture, supply `MPESA_PT_MONITOR_SCHEDULER_ENABLED=true` and the three `MPESA_PT_MONITOR_{MERCHANT_ID,APPLICATION_ID,ACTOR_USER_ID}` UUIDs, then run the preflight with `--verify-scheduler`. The tool checks syntax only; separately confirm the actor is an active platform admin and that merchant/application scope is correct.
5. In staging, manually run one isolated monitoring capture, and repeat it in the same UTC hour. Verify one run per tenant/app/hour, no duplicated alerts and no fund/provider calls.
6. Test cross-tenant access denial, read-only history, alert acknowledgement audit, and that no alert triggers an outbound notification.
7. Confirm direct M-PESA and Golink adapters remain unchanged and test their existing sandbox regressions.
8. Review remaining high-severity unresolved alerts before a production monitoring rollout; obtain the operational owner's approval.

## Explicit fail-closed boundaries

- No scheduler is activated by this preflight.
- The optional single-shot runner is disabled unless its existing opt-in flag is set.
- Monitoring acknowledgement does not resolve an uncertain payment.
- Monitoring results cannot be treated as provider settlement proof.
- Live pass-through dispatch and notification delivery must remain disabled until separate provider certification, legal/contract approvals, ledger and reconciliation testing, deployment review and documented sign-off.

## Outstanding proof

Record actual CI run, disposable migration/restore outputs, staging authorization and tenant-isolation results, provider simulator tests, and production owner approval **before** declaring a release ready.
