"""Prepare and cancel audit-backed, *non-sendable* investigation notices.

Platform administrators can prepare one generic notice per case / authorized
recipient. This is not an SMS/email/push dispatcher and carries no delivery
destination, customer identifiers, amount, status success or provider details.
The caller owns the SQL transaction; all writes/audit commit atomically.
"""
from __future__ import annotations

from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import User
from database.models.mpesa_pass_through_exception import MpesaPassThroughExceptionCase
from database.models.mpesa_pass_through_notification import MpesaPassThroughNotificationDraft
from services.audit import write_audit
from services.mpesa_pass_through_exceptions import draft_exception_notification
from services.mpesa_pass_through_lifecycle import TransactionError

TEMPLATE = "investigation_under_review"
VERSION = 1


def _platform_admin(db: Session, user_id: str) -> User:
    user = db.get(User, user_id) if user_id else None
    if not user or not user.is_active or user.role not in {
        "platform_admin", "platform_super_admin",
    }:
        raise TransactionError("Active platform administrator required")
    return user


def _case(db: Session, merchant_id: str, application_id: str, case_id: str):
    case = db.scalar(select(MpesaPassThroughExceptionCase).where(
        MpesaPassThroughExceptionCase.id == case_id,
        MpesaPassThroughExceptionCase.merchant_id == merchant_id,
        MpesaPassThroughExceptionCase.application_id == application_id,
    ).with_for_update())
    if case is None:
        raise TransactionError("Exception case unavailable in authorized scope")
    return case


def prepare_notification(
    db: Session, *, merchant_id: str, application_id: str, case_id: str,
    actor_user_id: str, recipient_user_id: str,
) -> MpesaPassThroughNotificationDraft:
    """Prepare solely for an active platform admin. Never dispatch.

    PostgreSQL case row locking serializes concurrent preparations for a
    case. The database unique constraint additionally prevents duplicate
    records across sessions; caller must roll back on an IntegrityError.
    """
    actor = _platform_admin(db, actor_user_id)
    recipient = _platform_admin(db, recipient_user_id)
    case = _case(db, merchant_id, application_id, case_id)
    if case.status == "closed":
        raise TransactionError("Cannot prepare an investigation notice for a closed case")
    draft = draft_exception_notification(case)
    if draft.safe_to_send:
        raise TransactionError("Unexpected notification delivery authorization")
    digest = sha256(draft.text.encode("utf-8")).hexdigest()
    existing = db.scalar(select(MpesaPassThroughNotificationDraft).where(
        MpesaPassThroughNotificationDraft.case_id == case.id,
        MpesaPassThroughNotificationDraft.recipient_user_id == recipient.id,
        MpesaPassThroughNotificationDraft.template == TEMPLATE,
        MpesaPassThroughNotificationDraft.version == VERSION,
    ).with_for_update())
    if existing:
        if (existing.merchant_id != merchant_id or
                existing.application_id != application_id or
                existing.body_sha256 != digest):
            raise TransactionError("Existing notification draft does not match approved template")
        return existing
    row = MpesaPassThroughNotificationDraft(
        case_id=case.id, merchant_id=merchant_id, application_id=application_id,
        recipient_user_id=recipient.id, created_by_user_id=actor.id,
        template=TEMPLATE, version=VERSION,
        body_sha256=digest, status="prepared",
    )
    db.add(row)
    db.flush()
    write_audit(
        db, actor_type="user", actor_id=actor.id,
        merchant_id=merchant_id, resource_type="mpesa_pt_notification_draft",
        resource_id=row.id, action="mpesa_pass_through.notice.prepared",
        metadata={"case_id": case.id, "recipient_user_id": recipient.id,
                  "template": TEMPLATE, "status": "prepared"},
    )
    return row


def cancel_notification(
    db: Session, *, merchant_id: str, application_id: str, draft_id: str,
    actor_user_id: str,
) -> MpesaPassThroughNotificationDraft:
    actor = _platform_admin(db, actor_user_id)
    row = db.scalar(select(MpesaPassThroughNotificationDraft).where(
        MpesaPassThroughNotificationDraft.id == draft_id,
        MpesaPassThroughNotificationDraft.merchant_id == merchant_id,
        MpesaPassThroughNotificationDraft.application_id == application_id,
    ).with_for_update())
    if not row:
        raise TransactionError("Notification draft not found in authorized scope")
    if row.status == "cancelled":
        return row
    if row.status != "prepared":
        raise TransactionError("Unsupported notification status")
    row.status = "cancelled"
    db.flush()
    write_audit(
        db, actor_type="user", actor_id=actor.id,
        merchant_id=merchant_id, resource_type="mpesa_pt_notification_draft",
        resource_id=row.id, action="mpesa_pass_through.notice.cancelled",
        metadata={"case_id": row.case_id, "status": "cancelled"},
    )
    return row


def list_notification_drafts(
    db: Session, *, merchant_id: str, application_id: str,
    case_id: str, limit: int = 100,
) -> list[MpesaPassThroughNotificationDraft]:
    if not 1 <= limit <= 500:
        raise ValueError("Invalid notification list limit")
    _case(db, merchant_id, application_id, case_id)
    return db.scalars(select(MpesaPassThroughNotificationDraft).where(
        MpesaPassThroughNotificationDraft.merchant_id == merchant_id,
        MpesaPassThroughNotificationDraft.application_id == application_id,
        MpesaPassThroughNotificationDraft.case_id == case_id,
    ).order_by(MpesaPassThroughNotificationDraft.created_at).limit(limit)).all()
