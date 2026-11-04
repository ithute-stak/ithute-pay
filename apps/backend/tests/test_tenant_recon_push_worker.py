"""Guarded push outbox: dedupe, recipient isolation, cancellation and retries."""
from datetime import datetime, timezone

from database.config.config import settings
from database.models import (
    ReconciliationItem, TenantReconciliationAlertPolicy,
    TenantReconciliationPushDelivery, TenantUserMembership, User,
)
from database.session import SessionLocal
from services import tenant_recon_push_worker as worker
from test_tenant_reconciliation_operations import _seed


def _setup(monkeypatch):
    own, foreign, investigator_id = _seed(role="owner")
    monkeypatch.setattr(settings, "ITHUTE_PUSH_ENABLED", True)
    monkeypatch.setattr(settings, "ITHUTE_PUSH_SERVICE_CLIENT_SECRET", "unit-test-placeholder")
    monkeypatch.setattr(settings, "ITHUTE_RECON_PUSH_DISPATCH_ENABLED", True)
    with SessionLocal() as db:
        owner = db.query(User).filter(User.email == "ops@example.com").one()
        investigator = db.get(User, investigator_id)
        owner.auth_user_id = "00000000-0000-0000-0000-000000000001"
        investigator.auth_user_id = "00000000-0000-0000-0000-000000000002"
        db.add(TenantReconciliationAlertPolicy(
            merchant_id=own, overdue_after_days=7, unassigned_after_days=2,
            overdue_enabled=True, unassigned_enabled=True, escalated_enabled=True,
        ))
        db.commit()
    return own, foreign, investigator_id


def test_delivery_stays_disabled_by_default_and_never_calls_provider(monkeypatch):
    own, _, _ = _setup(monkeypatch)
    monkeypatch.setattr(settings, "ITHUTE_RECON_PUSH_DISPATCH_ENABLED", False)
    monkeypatch.setattr(worker, "send_notification", lambda **kwargs: (_ for _ in ()).throw(
        AssertionError("Push must not run when disabled")))
    assert worker.run_once()["enabled"] is False
    with SessionLocal() as db:
        assert db.query(TenantReconciliationPushDelivery).count() == 0


def test_enqueue_once_and_send_only_to_eligible_tenant_users(monkeypatch):
    own, foreign, _ = _setup(monkeypatch)
    now = datetime.now(timezone.utc)
    deliveries = []
    with SessionLocal() as db:
        assert worker.enqueue_due(db, now) == 3
        assert worker.enqueue_due(db, now) == 0
        rows = db.query(TenantReconciliationPushDelivery).all()
        assert len(rows) == 3
        assert {row.merchant_id for row in rows} == {own}
        assert {row.alert_type for row in rows} == {"overdue", "unassigned", "escalated"}
    monkeypatch.setattr(worker, "send_notification", lambda **kwargs: (
        deliveries.append(kwargs) or {"message_id": "accepted"}
    ))
    result = worker.run_once()
    assert result["delivered"] == 3
    assert len(deliveries) == 3
    assert all(kwargs["route"] == "/business" for kwargs in deliveries)
    assert len({kwargs["idempotency_key"] for kwargs in deliveries}) == 3
    assert all("amount" not in kwargs["data"] for kwargs in deliveries)
    with SessionLocal() as db:
        assert db.query(TenantReconciliationPushDelivery).filter(
            TenantReconciliationPushDelivery.status == "delivered",
        ).count() == 3
        assert db.query(ReconciliationItem).filter(
            ReconciliationItem.merchant_id == own,
            ReconciliationItem.status == "mismatch",
        ).count() == 4


def test_failed_push_retries_without_new_duplicate(monkeypatch):
    own, _, _ = _setup(monkeypatch)
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        assert worker.enqueue_due(db, now) == 3
        claim = worker.claim_next(db, now)
    assert claim is not None
    def failed(**kwargs):
        raise worker.IthutePushUnavailable("provider down")
    monkeypatch.setattr(worker, "send_notification", failed)
    with SessionLocal() as db:
        assert worker.dispatch_one(db, *claim, now) == "pending"
        row = db.get(TenantReconciliationPushDelivery, claim[0])
        assert row.attempts == 1
        assert row.last_error_code == "push_unavailable"
        assert row.next_attempt_at > now
        assert worker.enqueue_due(db, now) == 0


def test_case_closed_before_dispatch_is_cancelled(monkeypatch):
    own, _, _ = _setup(monkeypatch)
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        worker.enqueue_due(db, now)
        claim = worker.claim_next(db, now)
        row = db.get(TenantReconciliationPushDelivery, claim[0])
        case = row.case_id
        from database.models import TenantReconciliationException
        investigation = db.get(TenantReconciliationException, case)
        investigation.investigation_status = "closed"
        db.commit()
    monkeypatch.setattr(worker, "send_notification", lambda **kwargs: (_ for _ in ()).throw(
        AssertionError("Closed case must not trigger push")))
    with SessionLocal() as db:
        assert worker.dispatch_one(db, *claim, now) == "cancelled"


def test_stale_worker_cannot_overwrite_reclaimed_lease(monkeypatch):
    """A delayed successful response must not clobber a later worker attempt."""
    from datetime import timedelta
    own, _, _ = _setup(monkeypatch)
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        worker.enqueue_due(db, now)
        claim = worker.claim_next(db, now)
    assert claim is not None

    def delayed_send(**kwargs):
        with SessionLocal() as other:
            row = other.get(TenantReconciliationPushDelivery, claim[0])
            row.attempts = claim[1] + 1
            row.status = "leased"
            row.lease_until = now + timedelta(minutes=3)
            other.commit()
        return {"id": "accepted-previous-attempt"}

    monkeypatch.setattr(worker, "send_notification", delayed_send)
    with SessionLocal() as db:
        assert worker.dispatch_one(db, *claim, now) == "skipped"
    with SessionLocal() as db:
        row = db.get(TenantReconciliationPushDelivery, claim[0])
        assert row.status == "leased"
        assert row.attempts == claim[1] + 1
        assert row.provider_message_id is None


def test_exhausted_expired_lease_is_reaped_without_sending(monkeypatch):
    from datetime import timedelta
    own, _, _ = _setup(monkeypatch)
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        worker.enqueue_due(db, now)
        row = db.query(TenantReconciliationPushDelivery).filter(
            TenantReconciliationPushDelivery.merchant_id == own,
        ).first()
        row.status = "leased"
        row.attempts = worker.MAX_ATTEMPTS
        row.lease_until = now - timedelta(minutes=1)
        row_id = row.id
        db.commit()
    monkeypatch.setattr(worker, "send_notification", lambda **kwargs: (_ for _ in ()).throw(
        AssertionError("Exhausted lease must not dispatch")))
    with SessionLocal() as db:
        worker.claim_next(db, now)
        row = db.get(TenantReconciliationPushDelivery, row_id)
        assert row.status == "failed"
        assert row.last_error_code == "lease_expired"
        assert row.lease_until is None
