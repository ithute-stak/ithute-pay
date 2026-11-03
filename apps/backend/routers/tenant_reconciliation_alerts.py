"""Tenant reconciliation in-app alerts and configurable thresholds.

Alerts are derived from existing case state when requested. This deliberately
does not send external push, email or SMS and does not mutate financial status.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.access_control import get_current_active_user
from database.models import (
    TenantReconciliationAlertAcknowledgement, TenantReconciliationAlertPolicy,
    TenantReconciliationException, TenantReconciliationPushDelivery,
    TenantUserMembership, User,
)
from database.session import get_db
from routers.tenant_portal import _allowed_tenant
from routers.tenant_reconciliation_operations import _utc
from services.audit import write_audit

router = APIRouter(prefix="/tenant-portal", tags=["Tenant Reconciliation Alerts"])
SETTERS = {"owner", "manager"}
TYPES = {"overdue", "unassigned", "escalated"}
MAX_CASES = 10000


class AlertPolicyChange(BaseModel):
    overdue_after_days: int = Field(ge=1, le=90)
    unassigned_after_days: int = Field(ge=1, le=90)
    overdue_enabled: bool = True
    unassigned_enabled: bool = True
    escalated_enabled: bool = True


def _member_role(db: Session, user: User, merchant_id: str) -> str:
    _allowed_tenant(db, user, merchant_id)
    return db.scalar(select(TenantUserMembership.role).where(
        TenantUserMembership.user_id == user.id,
        TenantUserMembership.merchant_id == merchant_id,
        TenantUserMembership.status == "active",
    )) or "viewer"


def _settings(policy: TenantReconciliationAlertPolicy | None) -> dict:
    if policy is None:
        return {
            "overdue_after_days": 7, "unassigned_after_days": 2,
            "overdue_enabled": True, "unassigned_enabled": True,
            "escalated_enabled": True,
        }
    return {
        "overdue_after_days": policy.overdue_after_days,
        "unassigned_after_days": policy.unassigned_after_days,
        "overdue_enabled": policy.overdue_enabled,
        "unassigned_enabled": policy.unassigned_enabled,
        "escalated_enabled": policy.escalated_enabled,
    }


def _policy(db: Session, merchant_id: str):
    return db.scalar(select(TenantReconciliationAlertPolicy).where(
        TenantReconciliationAlertPolicy.merchant_id == merchant_id,
    ))


@router.get("/merchants/{merchant_id}/reconciliation/alerts/settings")
def get_alert_settings(merchant_id: str, db: Session = Depends(get_db),
                       user: User = Depends(get_current_active_user)):
    _member_role(db, user, merchant_id)
    return _settings(_policy(db, merchant_id))


@router.put("/merchants/{merchant_id}/reconciliation/alerts/settings")
def set_alert_settings(merchant_id: str, payload: AlertPolicyChange,
                       db: Session = Depends(get_db),
                       user: User = Depends(get_current_active_user)):
    if _member_role(db, user, merchant_id) not in SETTERS:
        raise HTTPException(status_code=403, detail="Owner or manager role required")
    policy = db.scalar(select(TenantReconciliationAlertPolicy).where(
        TenantReconciliationAlertPolicy.merchant_id == merchant_id,
    ).with_for_update())
    if policy is None:
        policy = TenantReconciliationAlertPolicy(merchant_id=merchant_id)
        db.add(policy)
    for field, value in payload.model_dump().items():
        setattr(policy, field, value)
    policy.updated_by = user.id
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Alert settings changed concurrently; retry") from None
    write_audit(
        db, actor_type="user", actor_id=user.id,
        action="tenant_reconciliation_alert_policy.updated",
        resource_type="tenant_reconciliation_alert_policy",
        resource_id=policy.id, merchant_id=merchant_id,
        metadata=payload.model_dump(),
    )
    db.commit()
    return _settings(policy)


def _alerts(db: Session, merchant_id: str, user_id: str, now: datetime):
    rules = _settings(_policy(db, merchant_id))
    cases = db.scalars(select(TenantReconciliationException).where(
        TenantReconciliationException.merchant_id == merchant_id,
        TenantReconciliationException.investigation_status != "closed",
    ).order_by(TenantReconciliationException.created_at.desc()).limit(MAX_CASES + 1)).all()
    if len(cases) > MAX_CASES:
        raise HTTPException(status_code=413, detail="Too many active investigations to generate alerts")
    acknowledgements = {
        (ack.case_id, ack.alert_type): ack.acknowledged_at
        for ack in db.scalars(select(TenantReconciliationAlertAcknowledgement).where(
            TenantReconciliationAlertAcknowledgement.merchant_id == merchant_id,
            TenantReconciliationAlertAcknowledgement.user_id == user_id,
        )).all()
    }
    result = []
    for case in cases:
        age_days = max(0, (now.date() - _utc(case.created_at).date()).days)
        kinds = []
        if rules["overdue_enabled"] and age_days > rules["overdue_after_days"]:
            kinds.append("overdue")
        if (rules["unassigned_enabled"] and case.assigned_user_id is None
                and age_days > rules["unassigned_after_days"]):
            kinds.append("unassigned")
        if rules["escalated_enabled"] and case.investigation_status == "escalated":
            kinds.append("escalated")
        for kind in kinds:
            result.append({
                "id": f"{case.id}:{kind}",
                "case_id": case.id, "alert_type": kind,
                "age_days": age_days,
                "classification": case.classification,
                "investigation_status": case.investigation_status,
                "assigned_user_id": case.assigned_user_id,
                "acknowledged": (case.id, kind) in acknowledgements,
                "created_at": _utc(case.created_at).isoformat(),
            })
    return result


@router.get("/merchants/{merchant_id}/reconciliation/alerts")
def list_alerts(merchant_id: str,
                include_acknowledged: bool = Query(default=False),
                db: Session = Depends(get_db),
                user: User = Depends(get_current_active_user)):
    _member_role(db, user, merchant_id)
    rows = _alerts(db, merchant_id, user.id, datetime.now(timezone.utc))
    pending = [row for row in rows if not row["acknowledged"]]
    return {
        "unacknowledged_count": len(pending),
        "alerts": (rows if include_acknowledged else pending)[:200],
        "display_limit": 200,
        "delivery": "in_app_on_demand",
        "disclaimer": "Alerts are read-only operational indicators, not dispatched push or payment instructions.",
    }


@router.post("/merchants/{merchant_id}/reconciliation/alerts/{case_id}/{alert_type}/acknowledge")
def acknowledge_alert(merchant_id: str, case_id: str, alert_type: str,
                      db: Session = Depends(get_db),
                      user: User = Depends(get_current_active_user)):
    _member_role(db, user, merchant_id)
    if alert_type not in TYPES:
        raise HTTPException(status_code=404, detail="Alert not found")
    current = _alerts(db, merchant_id, user.id, datetime.now(timezone.utc))
    match = next((item for item in current
                  if item["case_id"] == case_id and item["alert_type"] == alert_type), None)
    if match is None:
        raise HTTPException(status_code=404, detail="Active alert not found")
    if match["acknowledged"]:
        return {"case_id": case_id, "alert_type": alert_type, "acknowledged": True}
    acknowledgement = TenantReconciliationAlertAcknowledgement(
        merchant_id=merchant_id, user_id=user.id,
        case_id=case_id, alert_type=alert_type,
        acknowledged_at=datetime.now(timezone.utc),
    )
    db.add(acknowledgement)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return {"case_id": case_id, "alert_type": alert_type, "acknowledged": True}
    write_audit(
        db, actor_type="user", actor_id=user.id,
        action="tenant_reconciliation_alert.acknowledged",
        resource_type="tenant_reconciliation_exception",
        resource_id=case_id, merchant_id=merchant_id,
        metadata={"alert_type": alert_type},
    )
    db.commit()
    return {"case_id": case_id, "alert_type": alert_type, "acknowledged": True}


@router.get("/merchants/{merchant_id}/reconciliation/alerts/delivery-status")
def my_push_delivery_status(
    merchant_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Scoped delivery counters; never expose recipient subjects or service tokens."""
    _member_role(db, user, merchant_id)
    from database.config.config import settings
    rows = db.execute(select(
        TenantReconciliationPushDelivery.status,
        func.count(TenantReconciliationPushDelivery.id),
    ).where(
        TenantReconciliationPushDelivery.merchant_id == merchant_id,
        TenantReconciliationPushDelivery.recipient_user_id == user.id,
    ).group_by(TenantReconciliationPushDelivery.status)).all()
    return {
        "delivery_enabled": bool(
            settings.ITHUTE_RECON_PUSH_DISPATCH_ENABLED
            and settings.ITHUTE_PUSH_ENABLED
            and settings.ITHUTE_PUSH_SERVICE_CLIENT_SECRET
        ),
        "channel": "ithute_push",
        "scope": "current_user",
        "statuses": {status: count for status, count in rows},
        "delivery_note": (
            "The separate background worker must be scheduled by the operator; "
            "enabling settings alone does not start delivery."
        ),
    }
