"""Tenant-only push delivery monitoring, with gated audited retry requests.

Retry only re-queues an existing failed outbox row. A separately scheduled,
opt-in worker does all network dispatch with the same idempotency key.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.access_control import get_current_active_user
from database.config.config import settings
from database.models import (
    TenantReconciliationException, TenantReconciliationPushDelivery, User,
)
from database.session import get_db
from routers.tenant_reconciliation_alerts import _member_role
from routers.tenant_reconciliation_operations import _utc
from services.audit import write_audit

router = APIRouter(prefix="/tenant-portal", tags=["Tenant Push Delivery Operations"])
MANAGERS = {"owner", "manager"}
MAX_ATTEMPTS = 5


def _enabled() -> bool:
    return bool(settings.ITHUTE_RECON_PUSH_DISPATCH_ENABLED
                and settings.ITHUTE_PUSH_ENABLED
                and settings.ITHUTE_PUSH_SERVICE_CLIENT_SECRET)


def _row(row: TenantReconciliationPushDelivery) -> dict:
    return {
        "id": row.id, "case_id": row.case_id,
        "recipient_user_id": row.recipient_user_id,
        "alert_type": row.alert_type,
        "status": row.status, "attempts": row.attempts,
        "manual_retries": row.manual_retries,
        "last_error_code": row.last_error_code,
        "next_attempt_at": row.next_attempt_at.isoformat() if row.next_attempt_at else None,
        "delivered_at": row.delivered_at.isoformat() if row.delivered_at else None,
        "updated_at": row.updated_at.isoformat(),
    }


@router.get("/merchants/{merchant_id}/reconciliation/alerts/deliveries")
def delivery_monitor(
    merchant_id: str,
    status: str | None = Query(default=None, pattern="^(pending|leased|delivered|failed|cancelled)$"),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    role = _member_role(db, user, merchant_id)
    # All active tenant members can see their own attempts; manager-level
    # roles may investigate all recipients inside the same tenant.
    scope = (TenantReconciliationPushDelivery.merchant_id == merchant_id,)
    if role not in MANAGERS:
        scope += (TenantReconciliationPushDelivery.recipient_user_id == user.id,)
    statement = select(TenantReconciliationPushDelivery).where(*scope)
    if status:
        statement = statement.where(TenantReconciliationPushDelivery.status == status)
    records = db.scalars(statement.order_by(
        TenantReconciliationPushDelivery.created_at.desc(),
        TenantReconciliationPushDelivery.id.desc(),
    ).limit(limit)).all()
    counts = db.execute(select(
        TenantReconciliationPushDelivery.status,
        func.count(TenantReconciliationPushDelivery.id),
    ).where(*scope).group_by(TenantReconciliationPushDelivery.status)).all()
    return {
        "delivery_enabled": _enabled(),
        "scope": "tenant" if role in MANAGERS else "current_user",
        "counts": {key: number for key, number in counts},
        "items": [_row(entry) for entry in records],
        "limit": limit,
        "delivery_note": "Queued retries are processed only by the separately enabled background worker.",
    }


@router.post("/merchants/{merchant_id}/reconciliation/alerts/deliveries/{delivery_id}/retry")
def retry_failed_delivery(
    merchant_id: str,
    delivery_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    if _member_role(db, user, merchant_id) not in MANAGERS:
        raise HTTPException(status_code=403, detail="Owner or manager role required")
    if not _enabled():
        raise HTTPException(status_code=409, detail="Reconciliation push delivery is disabled")
    row = db.scalar(select(TenantReconciliationPushDelivery).where(
        TenantReconciliationPushDelivery.id == delivery_id,
        TenantReconciliationPushDelivery.merchant_id == merchant_id,
    ).with_for_update())
    if row is None:
        raise HTTPException(status_code=404, detail="Delivery not found")
    if row.status != "failed" or row.attempts < MAX_ATTEMPTS:
        raise HTTPException(status_code=409, detail="Only exhausted failed deliveries can be retried")
    if row.manual_retries >= 1:
        raise HTTPException(status_code=409, detail="Manual retry allowance exhausted")
    case = db.scalar(select(TenantReconciliationException).where(
        TenantReconciliationException.id == row.case_id,
        TenantReconciliationException.merchant_id == merchant_id,
        TenantReconciliationException.investigation_status != "closed",
    ))
    if case is None:
        raise HTTPException(status_code=409, detail="The investigation is no longer active")
    # The worker will revalidate assignee, role, alert policy, tenant status
    # and acknowledgements before attempting the provider call.
    row.status = "pending"
    row.manual_retries += 1
    row.attempts = 0
    row.next_attempt_at = datetime.now(timezone.utc)
    row.lease_until = None
    row.last_error_code = None
    write_audit(
        db, actor_type="user", actor_id=user.id,
        action="tenant_reconciliation_push.retry_requested",
        resource_type="tenant_reconciliation_push_delivery", resource_id=row.id,
        merchant_id=merchant_id, metadata={"case_id": row.case_id, "alert_type": row.alert_type},
    )
    db.commit()
    return {"id": row.id, "status": "pending", "message": "Queued for gated background delivery"}
