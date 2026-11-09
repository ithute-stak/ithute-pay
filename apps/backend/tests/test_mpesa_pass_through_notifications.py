"""Phase 14: durable non-sendable operator notice draft safety."""
from sqlalchemy import func, select
import pytest
from sqlalchemy.exc import IntegrityError

from database.models import Application, AuditLog, Merchant, User
from database.models.mpesa_pass_through_notification import MpesaPassThroughNotificationDraft
from database.session import SessionLocal
from services.mpesa_pass_through_exceptions import open_exception
from services.mpesa_pass_through_lifecycle import TransactionError
from services.mpesa_pass_through_notifications import (
    prepare_notification, cancel_notification, list_notification_drafts,
)
from services.mpesa_pass_through_outbox import reserve_operation
from services.mpesa_pass_through_quotes import quote
from services.mpesa_pass_through_store import create_quote_record


def setup(db, suffix):
    merchant = Merchant(name="Notices " + suffix, slug="pt-notice-" + suffix)
    db.add(merchant); db.flush()
    app = Application(merchant_id=merchant.id, name="Notices " + suffix, environment="test")
    admin = User(email="notice-" + suffix + "@example.com", password_hash="no-login",
                 role="platform_admin", is_active=True)
    receiver = User(email="notice-" + suffix + "-recipient@example.com", password_hash="no-login",
                    role="platform_super_admin", is_active=True)
    unauthorized = User(email="notice-" + suffix + "-merchant@example.com",
                        password_hash="no-login", role="merchant_admin", is_active=True)
    db.add_all([app, admin, receiver, unauthorized]); db.flush()
    q = quote(tenant_id=merchant.id, direction="outgoing",
              principal="1000", approved=True)
    tx = create_quote_record(
        db, merchant_id=merchant.id, application_id=app.id,
        idempotency_key="notice-" + suffix,
        request={"amount": "1000"}, quote=q,
    )
    intent = reserve_operation(
        db, merchant_id=merchant.id, application_id=app.id,
        transaction_id=tx.id, leg="funding", reference="fund-" + suffix,
    )
    case = open_exception(
        db, merchant_id=merchant.id, application_id=app.id,
        intent_id=intent.id, actor_user_id=admin.id,
        classification="provider_unconfirmed",
    )
    return {
        "merchant_id": merchant.id, "application_id": app.id,
        "case_id": case.id, "actor_user_id": admin.id,
        "recipient_user_id": receiver.id,
    }, unauthorized.id


def test_prepare_twice_returns_same_non_deliverable_record():
    with SessionLocal() as db:
        ids, _ = setup(db, "repeat")
        a = prepare_notification(db, **ids)
        b = prepare_notification(db, **ids)
        assert a.id == b.id
        assert a.status == "prepared"
        assert len(a.body_sha256) == 64
        assert db.scalar(select(func.count(MpesaPassThroughNotificationDraft.id))) == 1
        assert db.scalar(select(func.count(AuditLog.id)).where(
            AuditLog.action == "mpesa_pass_through.notice.prepared"
        )) == 1
        assert not hasattr(a, "phone") and not hasattr(a, "delivery_status")
        assert not hasattr(a, "send_to") and not hasattr(a, "delivered_at")
        db.commit()
    with SessionLocal() as db:
        assert db.scalar(select(func.count(MpesaPassThroughNotificationDraft.id))) == 1


def test_cancel_is_audited_and_cannot_send():
    with SessionLocal() as db:
        ids, _ = setup(db, "cancel")
        row = prepare_notification(db, **ids)
        args = {
            "merchant_id": ids["merchant_id"], "application_id": ids["application_id"],
            "draft_id": row.id, "actor_user_id": ids["actor_user_id"],
        }
        a = cancel_notification(db, **args)
        b = cancel_notification(db, **args)
        assert a.id == b.id
        assert a.status == "cancelled"
        assert db.scalar(select(func.count(AuditLog.id)).where(
            AuditLog.action == "mpesa_pass_through.notice.cancelled"
        )) == 1


def test_recipient_and_actor_must_both_be_active_platform_admins():
    with SessionLocal() as db:
        ids, limited = setup(db, "roles")
        with pytest.raises(TransactionError):
            prepare_notification(db, **{**ids, "recipient_user_id": limited})
        with pytest.raises(TransactionError):
            prepare_notification(db, **{**ids, "actor_user_id": limited})
        assert db.scalar(select(func.count(MpesaPassThroughNotificationDraft.id))) == 0


def test_scoped_case_and_list_reject_other_merchant():
    with SessionLocal() as db:
        ids, _ = setup(db, "owner")
        other, _ = setup(db, "other")
        with pytest.raises(TransactionError):
            prepare_notification(db, **{**ids, "merchant_id": other["merchant_id"]})
        prepare_notification(db, **ids)
        with pytest.raises(TransactionError):
            list_notification_drafts(db, merchant_id=other["merchant_id"],
                                     application_id=other["application_id"], case_id=ids["case_id"])
        assert len(list_notification_drafts(
            db, merchant_id=ids["merchant_id"],
            application_id=ids["application_id"], case_id=ids["case_id"],
        )) == 1


def test_one_notice_per_case_recipient_template_enforced_by_database():
    with SessionLocal() as db:
        ids, _ = setup(db, "constraint")
        row = prepare_notification(db, **ids)
        duplicate = MpesaPassThroughNotificationDraft(
            case_id=row.case_id, merchant_id=row.merchant_id,
            application_id=row.application_id, recipient_user_id=row.recipient_user_id,
            created_by_user_id=row.created_by_user_id,
            template=row.template, version=row.version,
            body_sha256=row.body_sha256, status="prepared",
        )
        db.add(duplicate)
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


def test_drafts_are_not_prepared_for_closed_case():
    with SessionLocal() as db:
        ids, _ = setup(db, "closed")
        from database.models.mpesa_pass_through_exception import MpesaPassThroughExceptionCase
        case = db.get(MpesaPassThroughExceptionCase, ids["case_id"])
        case.status = "closed"
        db.flush()
        with pytest.raises(TransactionError, match="closed"):
            prepare_notification(db, **ids)
