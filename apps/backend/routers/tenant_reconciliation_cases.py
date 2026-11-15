"""Tenant reconciliation exception casework, separate from financial records.

Investigators may classify and discuss discrepancies, but cannot mutate the
authoritative reconciliation result, provider transaction or ledger state.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.access_control import get_current_active_user
from database.models import (
    ReconciliationItem, TenantReconciliationException,
    TenantReconciliationExceptionEvent, TenantUserMembership, User,
)
from database.session import get_db
from routers.tenant_portal import _allowed_tenant
from services.audit import write_audit

router = APIRouter(prefix="/tenant-portal", tags=["Tenant Reconciliation Casework"])
CLASSIFICATIONS = {
    "amount_mismatch", "missing_provider_record", "missing_gateway_record",
    "duplicate", "timing", "other",
}
STATUSES = {"open", "investigating", "escalated", "closed"}
WRITERS = {"owner", "manager", "finance"}


class ExceptionChange(BaseModel):
    classification: str = Field(max_length=32)
    investigation_status: str = Field(default="open", max_length=24)
    assigned_user_id: str | None = Field(default=None, max_length=36)
    evidence_reference: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=2000)


def _role(db: Session, user: User, merchant_id: str) -> str:
    _allowed_tenant(db, user, merchant_id)
    role = db.scalar(select(TenantUserMembership.role).where(
        TenantUserMembership.user_id == user.id,
        TenantUserMembership.merchant_id == merchant_id,
        TenantUserMembership.status == "active",
    ))
    return role or "viewer"


def _assignment(db: Session, merchant_id: str, user_id: str | None) -> None:
    if user_id is None:
        return
    assignee = db.get(User, user_id)
    active = db.scalar(select(TenantUserMembership.id).where(
        TenantUserMembership.user_id == user_id,
        TenantUserMembership.merchant_id == merchant_id,
        TenantUserMembership.status == "active",
        TenantUserMembership.role.in_(tuple(WRITERS)),
    ))
    if not assignee or not assignee.is_active or not active:
        raise HTTPException(status_code=422, detail="Assignee must be an active tenant investigator")


def _data(row: TenantReconciliationException) -> dict:
    return {
        "id": row.id, "reconciliation_item_id": row.reconciliation_item_id,
        "classification": row.classification,
        "investigation_status": row.investigation_status,
        "assigned_user_id": row.assigned_user_id,
        "evidence_reference": row.evidence_reference,
        "notes": row.notes,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _event(db: Session, row: TenantReconciliationException, user: User, action: str, detail: dict):
    db.add(TenantReconciliationExceptionEvent(
        merchant_id=row.merchant_id, exception_id=row.id,
        actor_user_id=user.id, action=action,
        detail=json.dumps(detail, sort_keys=True),
    ))
    write_audit(
        db, actor_type="user", actor_id=user.id,
        action=f"tenant_reconciliation_exception.{action}",
        resource_type="tenant_reconciliation_exception",
        resource_id=row.id, merchant_id=row.merchant_id,
        metadata={"reconciliation_item_id": row.reconciliation_item_id},
    )


@router.get("/merchants/{merchant_id}/reconciliation/review-queue")
def review_queue(
    merchant_id: str,
    investigation_status: str | None = Query(default=None),
    classification: str | None = Query(default=None),
    assigned_to: str | None = Query(default=None, max_length=36),
    unassigned_only: bool = Query(default=False),
    offset: int = Query(default=0, ge=0, le=100000),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Paginated operator work queue using existing audited investigations.

    Read-only projection: the authoritative reconciliation item and provider
    transaction remain untouched. Existing exception case endpoints own every
    state transition and maintain their history/audit trail.
    """
    _role(db, user, merchant_id)
    if investigation_status and investigation_status not in STATUSES:
        raise HTTPException(status_code=422, detail="Invalid investigation status")
    if classification and classification not in CLASSIFICATIONS:
        raise HTTPException(status_code=422, detail="Invalid classification")
    if assigned_to and unassigned_only:
        raise HTTPException(status_code=422, detail="Choose assignee or unassigned filter")
    statement = select(TenantReconciliationException, ReconciliationItem).join(
        ReconciliationItem,
        ReconciliationItem.id == TenantReconciliationException.reconciliation_item_id,
    ).where(
        TenantReconciliationException.merchant_id == merchant_id,
        ReconciliationItem.merchant_id == merchant_id,
    )
    if investigation_status:
        statement = statement.where(
            TenantReconciliationException.investigation_status == investigation_status)
    if classification:
        statement = statement.where(
            TenantReconciliationException.classification == classification)
    if assigned_to:
        statement = statement.where(
            TenantReconciliationException.assigned_user_id == assigned_to)
    if unassigned_only:
        statement = statement.where(
            TenantReconciliationException.assigned_user_id.is_(None))
    rows = db.execute(statement.order_by(
        TenantReconciliationException.created_at.desc(),
        TenantReconciliationException.id.desc(),
    ).offset(offset).limit(limit + 1)).all()
    items = []
    for case, reconciliation in rows[:limit]:
        mismatch = (
            reconciliation.expected_amount is not None
            and reconciliation.provider_amount is not None
            and reconciliation.expected_amount != reconciliation.provider_amount
        )
        urgent = case.classification in {"amount_mismatch", "duplicate"} or mismatch
        items.append({
            "case_id": case.id,
            "reconciliation_item_id": reconciliation.id,
            "investigation_status": case.investigation_status,
            "classification": case.classification,
            "priority": "urgent" if urgent else "normal",
            "assigned_user_id": case.assigned_user_id,
            "provider": reconciliation.provider,
            "currency": reconciliation.currency,
            "expected_amount": (
                str(reconciliation.expected_amount)
                if reconciliation.expected_amount is not None else None
            ),
            "provider_amount": (
                str(reconciliation.provider_amount)
                if reconciliation.provider_amount is not None else None
            ),
            "reconciliation_status": reconciliation.status,
            "created_at": case.created_at.isoformat(),
            "manual_review_required": case.investigation_status != "closed",
            "financial_action_authorized": False,
        })
    return {
        "merchant_id": merchant_id,
        "count": len(items),
        "offset": offset,
        "limit": limit,
        "has_more": len(rows) > limit,
        "items": items,
        "read_only": True,
        "financial_action_authorized": False,
        "independent_settlement_verified": False,
    }


@router.get("/merchants/{merchant_id}/reconciliation/exceptions")
def list_exceptions(merchant_id: str, db: Session = Depends(get_db),
                    user: User = Depends(get_current_active_user)):
    _role(db, user, merchant_id)
    rows = db.scalars(select(TenantReconciliationException).where(
        TenantReconciliationException.merchant_id == merchant_id,
    ).order_by(TenantReconciliationException.created_at.desc()).limit(200)).all()
    return [_data(row) for row in rows]


@router.get("/merchants/{merchant_id}/reconciliation/exceptions/{exception_id}/history")
def exception_history(merchant_id: str, exception_id: str,
                      db: Session = Depends(get_db),
                      user: User = Depends(get_current_active_user)):
    _role(db, user, merchant_id)
    row = db.scalar(select(TenantReconciliationException).where(
        TenantReconciliationException.id == exception_id,
        TenantReconciliationException.merchant_id == merchant_id,
    ))
    if row is None:
        raise HTTPException(status_code=404, detail="Case not found")
    history = db.scalars(select(TenantReconciliationExceptionEvent).where(
        TenantReconciliationExceptionEvent.merchant_id == merchant_id,
        TenantReconciliationExceptionEvent.exception_id == exception_id,
    ).order_by(TenantReconciliationExceptionEvent.created_at, TenantReconciliationExceptionEvent.id)).all()
    return [{
        "id": event.id, "action": event.action, "actor_user_id": event.actor_user_id,
        "detail": json.loads(event.detail), "created_at": event.created_at.isoformat(),
    } for event in history]


@router.post("/merchants/{merchant_id}/reconciliation/items/{item_id}/exception",
             status_code=201)
def create_exception(merchant_id: str, item_id: str, payload: ExceptionChange,
                     db: Session = Depends(get_db),
                     user: User = Depends(get_current_active_user)):
    if _role(db, user, merchant_id) not in WRITERS:
        raise HTTPException(status_code=403, detail="Investigator role required")
    if payload.classification not in CLASSIFICATIONS or payload.investigation_status != "open":
        raise HTTPException(status_code=422, detail="New cases must begin open with a valid classification")
    item = db.scalar(select(ReconciliationItem).where(
        ReconciliationItem.id == item_id, ReconciliationItem.merchant_id == merchant_id,
    ))
    if item is None:
        raise HTTPException(status_code=404, detail="Reconciliation item not found")
    _assignment(db, merchant_id, payload.assigned_user_id)
    row = TenantReconciliationException(
        merchant_id=merchant_id, reconciliation_item_id=item_id,
        classification=payload.classification, investigation_status="open",
        assigned_user_id=payload.assigned_user_id,
        evidence_reference=payload.evidence_reference,
        notes=payload.notes, created_by=user.id, updated_by=user.id,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A case already exists for this reconciliation item") from None
    _event(db, row, user, "created", {
        "classification": row.classification, "assigned_user_id": row.assigned_user_id,
        "evidence_reference": row.evidence_reference,
        "notes": row.notes,
    })
    db.commit()
    db.refresh(row)
    return _data(row)


@router.patch("/merchants/{merchant_id}/reconciliation/exceptions/{exception_id}")
def update_exception(merchant_id: str, exception_id: str, payload: ExceptionChange,
                     db: Session = Depends(get_db),
                     user: User = Depends(get_current_active_user)):
    if _role(db, user, merchant_id) not in WRITERS:
        raise HTTPException(status_code=403, detail="Investigator role required")
    if payload.classification not in CLASSIFICATIONS or payload.investigation_status not in STATUSES:
        raise HTTPException(status_code=422, detail="Invalid classification or investigation status")
    row = db.scalar(select(TenantReconciliationException).where(
        TenantReconciliationException.id == exception_id,
        TenantReconciliationException.merchant_id == merchant_id,
    ).with_for_update())
    if row is None:
        raise HTTPException(status_code=404, detail="Case not found")
    if row.investigation_status == "closed":
        raise HTTPException(status_code=409, detail="Closed cases cannot be changed")
    # Closing is an administrative investigation status, NEVER financial settlement.
    if payload.investigation_status == "closed" and not payload.evidence_reference:
        raise HTTPException(status_code=422, detail="Closing a case requires an evidence reference")
    _assignment(db, merchant_id, payload.assigned_user_id)
    previous = {
        "classification": row.classification, "investigation_status": row.investigation_status,
        "assigned_user_id": row.assigned_user_id, "evidence_reference": row.evidence_reference,
        "notes": row.notes,
    }
    row.classification = payload.classification
    row.investigation_status = payload.investigation_status
    row.assigned_user_id = payload.assigned_user_id
    row.evidence_reference = payload.evidence_reference
    row.notes = payload.notes
    row.updated_by = user.id
    _event(db, row, user, "updated", {
        "before": previous,
        "after": {
            "classification": row.classification,
            "investigation_status": row.investigation_status,
            "assigned_user_id": row.assigned_user_id,
            "evidence_reference": row.evidence_reference, "notes": row.notes,
        },
    })
    db.commit()
    db.refresh(row)
    return _data(row)
