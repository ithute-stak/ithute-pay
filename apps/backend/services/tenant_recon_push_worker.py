"""Opt-in, one-shot reconciliation push outbox worker.

Run only as an explicitly scheduled separate process:
  ITHUTE_RECON_PUSH_DISPATCH_ENABLED=true python -m services.tenant_recon_push_worker

The default is OFF. This module is never invoked by payment routes or web
requests. Provider messages are idempotent across retries with stable keys.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.config.config import settings
from database.models import (
    Merchant, TenantMerchantContract, TenantReconciliationAlertAcknowledgement,
    TenantReconciliationAlertPolicy, TenantReconciliationException,
    TenantReconciliationPushDelivery, TenantUserMembership, User,
)
from database.session import SessionLocal
from routers.tenant_reconciliation_operations import _utc
from services.ithute_push import IthutePushDisabled, IthutePushUnavailable, send_notification

MAX_ATTEMPTS = 5
LEASE_SECONDS = 120
RETRY_BASE_SECONDS = 60


def enabled() -> bool:
    return bool(settings.ITHUTE_RECON_PUSH_DISPATCH_ENABLED and settings.ITHUTE_PUSH_ENABLED
                and settings.ITHUTE_PUSH_SERVICE_CLIENT_SECRET)


def _eligible_cases(db: Session, now: datetime):
    # No implicit enrollment: business must have explicitly saved an alert policy.
    rows = db.execute(select(TenantReconciliationException, TenantReconciliationAlertPolicy)
        .join(TenantReconciliationAlertPolicy,
              TenantReconciliationAlertPolicy.merchant_id == TenantReconciliationException.merchant_id)
        .join(Merchant, Merchant.id == TenantReconciliationException.merchant_id)
        .join(TenantMerchantContract,
              TenantMerchantContract.tenant_merchant_id == TenantReconciliationException.merchant_id)
        .where(TenantReconciliationException.investigation_status != "closed",
               Merchant.status == "active",
               TenantMerchantContract.status == "approved",
               TenantMerchantContract.kyc_status == "verified")
        .limit(10001)).all()
    if len(rows) > 10000:
        raise RuntimeError("Reconciliation push scan exceeded safe bound")
    for case, policy in rows:
        days = max(0, (now.date() - _utc(case.created_at).date()).days)
        kinds = []
        if policy.overdue_enabled and days > policy.overdue_after_days:
            kinds.append("overdue")
        if policy.unassigned_enabled and case.assigned_user_id is None and days > policy.unassigned_after_days:
            kinds.append("unassigned")
        if policy.escalated_enabled and case.investigation_status == "escalated":
            kinds.append("escalated")
        for kind in kinds:
            yield case, kind


def enqueue_due(db: Session, now: datetime) -> int:
    """Create exactly one outbox item per case, alert type and eligible recipient."""
    if not enabled():
        return 0
    count = 0
    for case, kind in _eligible_cases(db, now):
        query = (select(User.id, User.auth_user_id, TenantUserMembership.role)
                 .join(TenantUserMembership, TenantUserMembership.user_id == User.id)
                 .where(TenantUserMembership.merchant_id == case.merchant_id,
                        TenantUserMembership.status == "active",
                        TenantUserMembership.role.in_(("owner", "manager", "finance")),
                        User.is_active.is_(True),
                        User.auth_user_id.is_not(None)))
        for user_id, recipient_sub, role in db.execute(query).all():
            # Assigned investigator receives overdue alert. Owners/managers
            # receive unassigned and escalated alerts; no tenant-wide broadcast.
            if kind == "overdue" and user_id != case.assigned_user_id:
                continue
            if kind in {"unassigned", "escalated"} and role not in {"owner", "manager"}:
                continue
            ack = db.scalar(select(TenantReconciliationAlertAcknowledgement.id).where(
                TenantReconciliationAlertAcknowledgement.merchant_id == case.merchant_id,
                TenantReconciliationAlertAcknowledgement.case_id == case.id,
                TenantReconciliationAlertAcknowledgement.user_id == user_id,
                TenantReconciliationAlertAcknowledgement.alert_type == kind,
            ))
            if ack:
                continue
            present = db.scalar(select(TenantReconciliationPushDelivery.id).where(
                TenantReconciliationPushDelivery.merchant_id == case.merchant_id,
                TenantReconciliationPushDelivery.case_id == case.id,
                TenantReconciliationPushDelivery.recipient_user_id == user_id,
                TenantReconciliationPushDelivery.alert_type == kind,
            ))
            if present:
                continue
            try:
                with db.begin_nested():
                    db.add(TenantReconciliationPushDelivery(
                        merchant_id=case.merchant_id, case_id=case.id,
                        recipient_user_id=user_id, alert_type=kind,
                        status="pending", attempts=0, next_attempt_at=now,
                    ))
                    db.flush()
                count += 1
            except IntegrityError:
                # Unique constraint wins concurrent scheduling races.
                pass
    db.commit()
    return count


def claim_next(db: Session, now: datetime):
    """Lease one due outbox item without a network call while holding a lock."""
    # A worker may die after its last attempt, leaving a leased row forever.
    # Reap only expired, exhausted leases; do not re-dispatch them.
    db.execute(update(TenantReconciliationPushDelivery).where(
        TenantReconciliationPushDelivery.status == "leased",
        TenantReconciliationPushDelivery.attempts >= MAX_ATTEMPTS,
        TenantReconciliationPushDelivery.lease_until <= now,
    ).values(status="failed", lease_until=None, last_error_code="lease_expired"))
    row = db.scalar(select(TenantReconciliationPushDelivery).where(
        or_(
            (TenantReconciliationPushDelivery.status == "pending") &
            (or_(TenantReconciliationPushDelivery.next_attempt_at.is_(None),
                 TenantReconciliationPushDelivery.next_attempt_at <= now)),
            (TenantReconciliationPushDelivery.status == "leased") &
            (TenantReconciliationPushDelivery.lease_until <= now),
        ),
        TenantReconciliationPushDelivery.attempts < MAX_ATTEMPTS,
    ).order_by(TenantReconciliationPushDelivery.created_at, TenantReconciliationPushDelivery.id)
        .with_for_update(skip_locked=True).limit(1))
    if row is None:
        return None
    row.status = "leased"
    row.attempts += 1
    row.lease_until = now + timedelta(seconds=LEASE_SECONDS)
    db.commit()
    return row.id, row.attempts


def dispatch_one(db: Session, delivery_id: str, attempt: int, now: datetime) -> str:
    row = db.scalar(select(TenantReconciliationPushDelivery).where(
        TenantReconciliationPushDelivery.id == delivery_id,
    ))
    if row is None or row.status != "leased" or row.attempts != attempt:
        return "skipped"
    case = db.scalar(select(TenantReconciliationException).where(
        TenantReconciliationException.id == row.case_id,
        TenantReconciliationException.merchant_id == row.merchant_id,
        TenantReconciliationException.investigation_status != "closed",
    ))
    user = db.scalar(select(User).join(
        TenantUserMembership,
        (TenantUserMembership.user_id == User.id) &
        (TenantUserMembership.merchant_id == row.merchant_id),
    ).where(
        User.id == row.recipient_user_id, User.is_active.is_(True),
        User.auth_user_id.is_not(None),
        TenantUserMembership.status == "active",
        TenantUserMembership.role.in_(("owner", "manager", "finance")),
    ))
    policy = db.scalar(select(TenantReconciliationAlertPolicy).where(
        TenantReconciliationAlertPolicy.merchant_id == row.merchant_id,
    ))
    merchant = db.get(Merchant, row.merchant_id)
    contract = db.scalar(select(TenantMerchantContract.id).where(
        TenantMerchantContract.tenant_merchant_id == row.merchant_id,
        TenantMerchantContract.status == "approved",
        TenantMerchantContract.kyc_status == "verified",
    ))
    days = max(0, (now.date() - _utc(case.created_at).date()).days) if case else 0
    active = bool(
        case and user and policy and merchant and merchant.status == "active" and contract
        and (
            (row.alert_type == "overdue" and policy.overdue_enabled
             and user.id == case.assigned_user_id and days > policy.overdue_after_days)
            or (row.alert_type == "unassigned" and policy.unassigned_enabled
                and case.assigned_user_id is None and days > policy.unassigned_after_days)
            or (row.alert_type == "escalated" and policy.escalated_enabled
                and case.investigation_status == "escalated")
        )
    )
    if active and row.alert_type != "overdue":
        role = db.scalar(select(TenantUserMembership.role).where(
            TenantUserMembership.user_id == user.id,
            TenantUserMembership.merchant_id == row.merchant_id,
            TenantUserMembership.status == "active",
        ))
        active = role in {"owner", "manager"}
    acknowledged = db.scalar(select(TenantReconciliationAlertAcknowledgement.id).where(
        TenantReconciliationAlertAcknowledgement.merchant_id == row.merchant_id,
        TenantReconciliationAlertAcknowledgement.case_id == row.case_id,
        TenantReconciliationAlertAcknowledgement.user_id == row.recipient_user_id,
        TenantReconciliationAlertAcknowledgement.alert_type == row.alert_type,
    ))
    # A reclaimed lease has a newer attempt number; never allow an old
    # worker to overwrite its state after a delayed provider response.
    def finalize(values: dict, outcome: str) -> str:
        changed = db.execute(update(TenantReconciliationPushDelivery).where(
            TenantReconciliationPushDelivery.id == delivery_id,
            TenantReconciliationPushDelivery.status == "leased",
            TenantReconciliationPushDelivery.attempts == attempt,
        ).values(**values)).rowcount
        db.commit()
        return outcome if changed else "skipped"

    if not active or acknowledged or not enabled():
        return finalize({"status": "cancelled", "lease_until": None}, "cancelled")
    # Do not include financial values, customer data or evidence notes.
    try:
        result = send_notification(
            recipient_sub=user.auth_user_id,
            title="IthutePay reconciliation investigation",
            body=f"Your business has a {row.alert_type} reconciliation investigation.",
            route="/business",
            data={"source": "ithute-pay", "kind": "tenant-reconciliation",
                  "case_id": row.case_id, "alert_type": row.alert_type},
            idempotency_key=f"recon-push:{row.id}",
        )
    except (IthutePushDisabled, IthutePushUnavailable):
        return finalize({
            "status": "failed" if attempt >= MAX_ATTEMPTS else "pending",
            "last_error_code": "push_unavailable",
            "next_attempt_at": (now + timedelta(seconds=RETRY_BASE_SECONDS * (2 ** (attempt - 1))))
            if attempt < MAX_ATTEMPTS else None,
            "lease_until": None,
        }, "failed" if attempt >= MAX_ATTEMPTS else "pending")
    return finalize({
        "status": "delivered",
        "delivered_at": now,
        "lease_until": None,
        "last_error_code": None,
        "provider_message_id": str(result.get("id") or result.get("message_id") or "")[:200] or None,
    }, "delivered")


def run_once() -> dict:
    if not enabled():
        return {"enabled": False, "enqueued": 0, "processed": 0}
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        created = enqueue_due(db, now)
    counts = {"enabled": True, "enqueued": created, "processed": 0,
              "delivered": 0, "pending": 0, "failed": 0, "cancelled": 0}
    for _ in range(settings.ITHUTE_RECON_PUSH_BATCH_SIZE):
        with SessionLocal() as db:
            lease = claim_next(db, datetime.now(timezone.utc))
        if lease is None:
            break
        with SessionLocal() as db:
            state = dispatch_one(db, *lease, datetime.now(timezone.utc))
        counts["processed"] += 1
        if state in counts:
            counts[state] += 1
    return counts


if __name__ == "__main__":
    # Scheduled by operator after approving push, identities, and migration.
    print(run_once())
