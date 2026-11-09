"""Recovery inbox tests operate on disposable DB and never call a provider."""
from datetime import datetime, timedelta, timezone

import pytest

from database.models import Application, Merchant
from database.models.mpesa_pass_through_outbox import MpesaPassThroughOperationIntent
from database.session import SessionLocal
from services.mpesa_pass_through_identity import bind_leg_identity
from services.mpesa_pass_through_lifecycle import TransactionError
from services.mpesa_pass_through_outbox import reserve_operation
from services.mpesa_pass_through_quotes import quote
from services.mpesa_pass_through_recovery_inbox import (
    recovery_summary, scan_recovery_inbox,
)
from services.mpesa_pass_through_store import create_quote_record


def record(db, suffix, ref):
    merchant = Merchant(name="Recovery " + suffix, slug="pt-inbox-" + suffix)
    db.add(merchant)
    db.flush()
    app = Application(merchant_id=merchant.id, name="Recovery " + suffix, environment="test")
    db.add(app)
    db.flush()
    q = quote(tenant_id=merchant.id, direction="outgoing",
              principal="1000.00", approved=True)
    txn = create_quote_record(
        db, merchant_id=merchant.id, application_id=app.id,
        idempotency_key="recovery-" + suffix, request={"amount": "1000.00"}, quote=q,
    )
    kw = dict(merchant_id=merchant.id, application_id=app.id,
              transaction_id=txn.id)
    intent = reserve_operation(db, **kw, leg="funding", reference=ref)
    return kw, intent


def scan(db, kw, **kwargs):
    return scan_recovery_inbox(db, merchant_id=kw["merchant_id"],
                               application_id=kw["application_id"], **kwargs)


def test_unbound_stale_operation_requires_manual_review():
    with SessionLocal() as db:
        kw, intent = record(db, "unbound", "f-unbound")
        now = datetime.now(timezone.utc) + timedelta(minutes=15)
        result = scan(db, kw, now=now, age_seconds=60)
        assert len(result) == 1
        assert result[0].action == "manual_review"
        assert result[0].reference == intent.reference
        assert result[0].age_seconds >= 60
        assert recovery_summary(result)["manual_review"] == 1


def test_bound_stale_operation_uses_same_reference_without_dispatch():
    with SessionLocal() as db:
        kw, intent = record(db, "bound", "original-ref")
        bind_leg_identity(db, **kw, leg="funding",
                          source_party="TENANT", destination_party="PLATFORM")
        result = scan(db, kw, now=datetime.now(timezone.utc) + timedelta(minutes=20))
        assert len(result) == 1
        assert result[0].action == "query_original_reference"
        assert result[0].reference == "original-ref"
        assert intent.submitted_at is None
        assert intent.provider_operation_id is None


def test_recent_operation_is_not_stale():
    with SessionLocal() as db:
        kw, _ = record(db, "recent", "f-recent")
        assert scan(db, kw, age_seconds=300) == []


def test_closed_operation_never_appears():
    with SessionLocal() as db:
        kw, intent = record(db, "closed", "f-closed")
        intent.state = "closed"
        db.flush()
        assert scan(db, kw, now=datetime.now(timezone.utc) + timedelta(hours=1)) == []


def test_other_tenant_cannot_see_recovery_records():
    with SessionLocal() as db:
        owner, _ = record(db, "owner", "owner-ref")
        outsider, _ = record(db, "outsider", "outsider-ref")
        now = datetime.now(timezone.utc) + timedelta(hours=1)
        items = scan(db, owner, now=now)
        assert len(items) == 1
        assert items[0].merchant_id == owner["merchant_id"]
        assert items[0].reference == "owner-ref"
        assert "outsider-ref" not in [item.reference for item in items]


def test_recovery_does_not_change_outbox_state():
    with SessionLocal() as db:
        kw, intent = record(db, "read-only", "f-read")
        intent.state = "needs_reconciliation"
        db.flush()
        before = intent.state
        items = scan(db, kw, now=datetime.now(timezone.utc) + timedelta(hours=1))
        assert items[0].state == before
        assert intent.state == before
        assert intent.provider_operation_id is None


@pytest.mark.parametrize("age,limit", [(1, 100), (0, 100), (300, 0), (300, 501)])
def test_invalid_queue_limits_rejected(age, limit):
    with SessionLocal() as db:
        kw, _ = record(db, "invalid-" + str(age) + "-" + str(limit), "safe-ref")
        with pytest.raises(ValueError):
            scan(db, kw, age_seconds=age, limit=limit)


def test_missing_authenticated_scope_rejected():
    with SessionLocal() as db:
        with pytest.raises(TransactionError):
            scan_recovery_inbox(db, merchant_id="", application_id="")
