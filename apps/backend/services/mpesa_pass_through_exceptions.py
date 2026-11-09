"""Audited operator review for M-Pesa pass-through recovery exceptions.

Operator metadata cannot approve, resend, settle, refund, reverse or confirm a
payment. No API routes are registered; trusted callers must use authenticated
operator identity, never a client-provided actor ID.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import User
from database.models.mpesa_pass_through_exception import (
    MpesaPassThroughExceptionCase, MpesaPassThroughExceptionEvent,
)
from database.models.mpesa_pass_through_outbox import MpesaPassThroughOperationIntent
from services.audit import write_audit
from services.mpesa_pass_through_lifecycle import TransactionError

_CLASSIFICATIONS = {
    "missing_binding", "provider_unconfirmed", "identity_mismatch",
    "duplicate_receipt", "other",
}
_STATES = {"open", "investigating", "escalated", "closed"}
_ACTION = {
    "investigating": "investigating", "escalated": "escalated", "closed": "closed",
}


def _operator(db: Session, actor_user_id: str) -> User:
    user = db.get(User, actor_user_id) if actor_user_id else None
    if user is None or not user.is_active or user.role not in {
        "platform_admin", "platform_super_admin",
    }:
        raise TransactionError("Authorized active platform operator required")
    return user


def _intent(db: Session, *, merchant_id: str, application_id: str,
            intent_id: str) -> MpesaPassThroughOperationIntent:
    row = db.scalar(select(MpesaPassThroughOperationIntent).where(
        MpesaPassThroughOperationIntent.id == intent_id,
        MpesaPassThroughOperationIntent.merchant_id == merchant_id,
        MpesaPassThroughOperationIntent.application_id == application_id,
    ).with_for_update())
    if row is None:
        raise TransactionError("Intent not found in tenant and application scope")
    return row


def _event(db: Session, case: MpesaPassThroughExceptionCase, actor: User,
           action: str, detail: str) -> None:
    db.add(MpesaPassThroughExceptionEvent(
        case_id=case.id, merchant_id=case.merchant_id, actor_user_id=actor.id,
        action=action, detail=detail,
    ))
    write_audit(
        db, actor_type="user", actor_id=actor.id,
        action="mpesa_pass_through.exception." + action,
        resource_type="mpesa_pt_exception_case", resource_id=case.id,
        merchant_id=case.merchant_id,
        metadata={"intent_id": case.intent_id, "action": action},
    )
    db.flush()


def open_exception(
    db: Session, *, merchant_id: str, application_id: str,
    intent_id: str, actor_user_id: str, classification: str,
) -> MpesaPassThroughExceptionCase:
    actor = _operator(db, actor_user_id)
    if classification not in _CLASSIFICATIONS:
        raise TransactionError("Unsupported exception classification")
    intent = _intent(db, merchant_id=merchant_id, application_id=application_id,
                     intent_id=intent_id)
    if intent.state == "closed":
        raise TransactionError("Cannot open recovery exception for completed operation")
    existing = db.scalar(select(MpesaPassThroughExceptionCase).where(
        MpesaPassThroughExceptionCase.intent_id == intent_id,
    ).with_for_update())
    if existing is not None:
        if existing.classification != classification:
            raise TransactionError("Exception already exists with different classification")
        return existing
    case = MpesaPassThroughExceptionCase(
        intent_id=intent.id, merchant_id=merchant_id, application_id=application_id,
        classification=classification, status="open",
        created_by_user_id=actor.id, updated_by_user_id=actor.id,
    )
    db.add(case)
    db.flush()
    _event(db, case, actor, "opened", "Investigation opened; no financial state changed")
    return case


def review_exception(
    db: Session, *, merchant_id: str, application_id: str,
    case_id: str, actor_user_id: str, status: str,
    evidence_reference: str | None = None,
) -> MpesaPassThroughExceptionCase:
    actor = _operator(db, actor_user_id)
    if status not in _ACTION:
        raise TransactionError("Unsupported exception transition")
    case = db.scalar(select(MpesaPassThroughExceptionCase).where(
        MpesaPassThroughExceptionCase.id == case_id,
        MpesaPassThroughExceptionCase.merchant_id == merchant_id,
        MpesaPassThroughExceptionCase.application_id == application_id,
    ).with_for_update())
    if case is None:
        raise TransactionError("Exception not found in authorized scope")
    if case.status == "closed" or (
        case.status == status and status != "closed"
    ):
        raise TransactionError("No valid exception state transition")
    allowed = {
        "open": {"investigating", "escalated"},
        "investigating": {"escalated", "closed"},
        "escalated": {"investigating", "closed"},
    }
    if status not in allowed.get(case.status, set()):
        raise TransactionError("Invalid exception state transition")
    if status == "closed":
        intent = _intent(db, merchant_id=merchant_id, application_id=application_id,
                         intent_id=case.intent_id)
        if intent.state != "closed":
            raise TransactionError("Cannot close an unresolved financial operation")
        if (not evidence_reference or len(evidence_reference) < 8
                or len(evidence_reference) > 180):
            raise TransactionError("Closure requires non-sensitive verified evidence reference")
        case.evidence_reference = evidence_reference
    case.status = status
    case.updated_by_user_id = actor.id
    db.flush()
    _event(db, case, actor, _ACTION[status],
           "Operator investigation metadata updated; no transfer or posting changed")
    return case


@dataclass(frozen=True)
class NotificationDraft:
    event: str
    text: str
    safe_to_send: bool = False


def draft_exception_notification(case: MpesaPassThroughExceptionCase) -> NotificationDraft:
    """Internal generic wording only; never asserts payment success.

    All drafts are non-sendable: no SMS/email gateway, destination or PII.
    """
    if case.status not in _STATES:
        raise TransactionError("Unrecognized exception status")
    return NotificationDraft(
        event="mpesa_pass_through.investigation",
        text="A payment is under review. Please contact the merchant for an update.",
        safe_to_send=False,
    )
