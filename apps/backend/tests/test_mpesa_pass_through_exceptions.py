"""Operator exception cases never change financial state or send notices."""
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from database.models import Application, AuditLog, Merchant, User
from database.models.mpesa_pass_through_exception import (
    MpesaPassThroughExceptionCase, MpesaPassThroughExceptionEvent,
)
from database.session import SessionLocal
from services.mpesa_pass_through_exceptions import (
    open_exception, review_exception, draft_exception_notification,
)
from services.mpesa_pass_through_lifecycle import TransactionError
from services.mpesa_pass_through_outbox import reserve_operation
from services.mpesa_pass_through_quotes import quote
from services.mpesa_pass_through_store import create_quote_record


def setup(db, name):
    m = Merchant(name="Case " + name, slug="pt-exception-" + name)
    db.add(m); db.flush()
    a = Application(merchant_id=m.id, name="Case " + name, environment="test")
    admin = User(email=name + "@case.test", password_hash="no-login", role="platform_admin",
                 full_name="Case reviewer", is_active=True)
    employee = User(email=name + "-employee@case.test", password_hash="no-login",
                    role="merchant_admin", is_active=True)
    db.add_all([a,admin,employee]); db.flush()
    q = quote(tenant_id=m.id, direction="outgoing", principal="1000", approved=True)
    tx = create_quote_record(
        db, merchant_id=m.id, application_id=a.id,
        idempotency_key="exception-1", request={"principal": "1000"}, quote=q,
    )
    intent = reserve_operation(
        db, merchant_id=m.id, application_id=a.id,
        transaction_id=tx.id, leg="funding", reference="case-funding",
    )
    return dict(merchant_id=m.id, application_id=a.id,
                intent_id=intent.id, actor_user_id=admin.id), intent, employee


def test_open_case_writes_audit_and_remains_idempotent():
    with SessionLocal() as db:
        kw, intent, _ = setup(db, "open")
        case = open_exception(db, **kw, classification="provider_unconfirmed")
        repeated = open_exception(db, **kw, classification="provider_unconfirmed")
        assert repeated.id == case.id
        assert case.status == "open"
        assert db.scalar(select(func.count(MpesaPassThroughExceptionCase.id))) == 1
        assert db.scalar(select(func.count(MpesaPassThroughExceptionEvent.id))) == 1
        assert db.scalar(select(func.count(AuditLog.id))) == 1
        assert intent.state == "reserved"
        assert intent.provider_operation_id is None


def test_investigation_escalation_with_append_only_events():
    with SessionLocal() as db:
        kw, intent, _ = setup(db, "escalate")
        case = open_exception(db, **kw, classification="missing_binding")
        first = review_exception(db, merchant_id=kw["merchant_id"],
                                 application_id=kw["application_id"],
                                 case_id=case.id, actor_user_id=kw["actor_user_id"],
                                 status="investigating")
        assert first.status == "investigating"
        review_exception(db, merchant_id=kw["merchant_id"],
                         application_id=kw["application_id"], case_id=case.id,
                         actor_user_id=kw["actor_user_id"], status="escalated")
        assert db.scalar(select(func.count(MpesaPassThroughExceptionEvent.id))) == 3
        assert db.scalar(select(func.count(AuditLog.id))) == 3
        assert intent.state == "reserved"


def test_cannot_close_unconfirmed_payment():
    with SessionLocal() as db:
        kw, _, _ = setup(db, "no-close")
        case = open_exception(db, **kw, classification="provider_unconfirmed")
        review_exception(db, merchant_id=kw["merchant_id"], application_id=kw["application_id"],
                         case_id=case.id, actor_user_id=kw["actor_user_id"],
                         status="investigating")
        with pytest.raises(TransactionError, match="unresolved"):
            review_exception(db, merchant_id=kw["merchant_id"],
                             application_id=kw["application_id"], case_id=case.id,
                             actor_user_id=kw["actor_user_id"], status="closed",
                             evidence_reference="verified-case-123")
        assert case.status == "investigating"


def test_closed_payment_allows_case_closure_with_reference_only():
    with SessionLocal() as db:
        kw, intent, _ = setup(db, "closed")
        case = open_exception(db, **kw, classification="provider_unconfirmed")
        review_exception(db, merchant_id=kw["merchant_id"], application_id=kw["application_id"],
                         case_id=case.id, actor_user_id=kw["actor_user_id"],
                         status="investigating")
        intent.state = "closed"
        db.flush()
        result = review_exception(db, merchant_id=kw["merchant_id"],
                                  application_id=kw["application_id"],
                                  case_id=case.id, actor_user_id=kw["actor_user_id"],
                                  status="closed", evidence_reference="evidence-ref-123")
        assert result.status == "closed"
        with pytest.raises(TransactionError):
            review_exception(db, merchant_id=kw["merchant_id"],
                             application_id=kw["application_id"], case_id=case.id,
                             actor_user_id=kw["actor_user_id"], status="investigating")


def test_unprivileged_user_cannot_open_case():
    with SessionLocal() as db:
        kw, _, employee = setup(db, "unauthorized")
        with pytest.raises(TransactionError, match="Authorized"):
            open_exception(db, **{**kw, "actor_user_id": employee.id},
                           classification="provider_unconfirmed")


def test_cross_tenant_case_rejected():
    with SessionLocal() as db:
        kw, _, _ = setup(db, "scoped")
        case = open_exception(db, **kw, classification="provider_unconfirmed")
        with pytest.raises(TransactionError):
            review_exception(db, merchant_id="different-tenant",
                             application_id=kw["application_id"], case_id=case.id,
                             actor_user_id=kw["actor_user_id"], status="investigating")


def test_unrecognized_classification_rejected():
    with SessionLocal() as db:
        kw, _, _ = setup(db, "bad-class")
        with pytest.raises(TransactionError, match="classification"):
            open_exception(db, **kw, classification="payment_paid")


def test_notification_draft_never_claims_success_or_sends():
    with SessionLocal() as db:
        kw, _, _ = setup(db, "notice")
        case = open_exception(db, **kw, classification="missing_binding")
        draft = draft_exception_notification(case)
        assert draft.safe_to_send is False
        assert "under review" in draft.text
        assert "successful" not in draft.text.lower()
        assert "payment received" not in draft.text.lower()
        assert "case-funding" not in draft.text
