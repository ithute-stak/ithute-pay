"""Platform-admin-only pass-through investigation API.

These routes expose only recovery/investigation metadata. No provider API,
money movement, webhook delivery, customer notification or journal updates.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.access_control import get_current_active_user
from database.models import User
from database.models.mpesa_pass_through_exception import MpesaPassThroughExceptionCase
from database.session import get_db
from services.mpesa_pass_through_exceptions import (
    draft_exception_notification, open_exception, review_exception,
)
from services.mpesa_pass_through_lifecycle import TransactionError
from services.mpesa_pass_through_recovery_inbox import (
    recovery_summary, scan_recovery_inbox,
)

router = APIRouter(prefix="/admin/mpesa-pass-through", tags=["Pass-through Operations"])


def _operator(user: User = Depends(get_current_active_user)) -> User:
    if str(user.role) not in {"platform_super_admin", "platform_admin"}:
        raise HTTPException(status_code=403, detail="Platform admin required")
    return user


class OpenCaseRequest(BaseModel):
    merchant_id: str = Field(min_length=36, max_length=36)
    application_id: str = Field(min_length=36, max_length=36)
    intent_id: str = Field(min_length=36, max_length=36)
    classification: str = Field(
        pattern="^(missing_binding|provider_unconfirmed|identity_mismatch|duplicate_receipt|other)$"
    )


class ReviewCaseRequest(BaseModel):
    merchant_id: str = Field(min_length=36, max_length=36)
    application_id: str = Field(min_length=36, max_length=36)
    status: str = Field(pattern="^(investigating|escalated|closed)$")
    evidence_reference: str | None = Field(default=None, max_length=180)


def _public_case(row: MpesaPassThroughExceptionCase) -> dict:
    return {
        "id": row.id, "intent_id": row.intent_id,
        "merchant_id": row.merchant_id, "application_id": row.application_id,
        "classification": row.classification, "status": row.status,
        "assignee_user_id": row.assignee_user_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("/recovery")
def recovery_inbox(
    merchant_id: str = Query(min_length=36, max_length=36),
    application_id: str = Query(min_length=36, max_length=36),
    age_seconds: int = Query(default=300, ge=30, le=2592000),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db), _: User = Depends(_operator),
):
    items = scan_recovery_inbox(
        db, merchant_id=merchant_id, application_id=application_id,
        age_seconds=age_seconds, limit=limit,
    )
    return {
        "summary": recovery_summary(items),
        "items": [
            {
                "intent_id": i.intent_id, "transaction_id": i.transaction_id,
                "leg": i.leg, "state": i.state,
                "age_seconds": i.age_seconds, "action": i.action,
                "reference": i.reference,
            }
            for i in items
        ],
    }


@router.get("/cases")
def list_cases(
    merchant_id: str = Query(min_length=36, max_length=36),
    application_id: str = Query(min_length=36, max_length=36),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db), _: User = Depends(_operator),
):
    cases = db.scalars(
        select(MpesaPassThroughExceptionCase).where(
            MpesaPassThroughExceptionCase.merchant_id == merchant_id,
            MpesaPassThroughExceptionCase.application_id == application_id,
        ).order_by(MpesaPassThroughExceptionCase.created_at.desc()).limit(limit)
    ).all()
    return [_public_case(c) for c in cases]


@router.post("/cases", status_code=201)
def create_case(
    payload: OpenCaseRequest, db: Session = Depends(get_db),
    user: User = Depends(_operator),
):
    try:
        case = open_exception(
            db, merchant_id=payload.merchant_id,
            application_id=payload.application_id, intent_id=payload.intent_id,
            classification=payload.classification, actor_user_id=user.id,
        )
        db.commit()
        db.refresh(case)
    except TransactionError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _public_case(case)


@router.post("/cases/{case_id}/review")
def review_case(
    case_id: str, payload: ReviewCaseRequest,
    db: Session = Depends(get_db), user: User = Depends(_operator),
):
    try:
        case = review_exception(
            db, merchant_id=payload.merchant_id,
            application_id=payload.application_id, case_id=case_id,
            actor_user_id=user.id, status=payload.status,
            evidence_reference=payload.evidence_reference,
        )
        db.commit()
        db.refresh(case)
    except TransactionError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _public_case(case)


@router.get("/cases/{case_id}/notification-preview")
def notification_preview(
    case_id: str,
    merchant_id: str = Query(min_length=36, max_length=36),
    application_id: str = Query(min_length=36, max_length=36),
    db: Session = Depends(get_db), _: User = Depends(_operator),
):
    case = db.scalar(select(MpesaPassThroughExceptionCase).where(
        MpesaPassThroughExceptionCase.id == case_id,
        MpesaPassThroughExceptionCase.merchant_id == merchant_id,
        MpesaPassThroughExceptionCase.application_id == application_id,
    ))
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    draft = draft_exception_notification(case)
    return {"event": draft.event, "text": draft.text,
            "safe_to_send": False, "delivery_enabled": False}
