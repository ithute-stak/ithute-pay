"""Phase 16: read-only recovery monitoring and policy regression."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from database.models import Application, Merchant, User
from database.models.mpesa_pass_through_exception import MpesaPassThroughExceptionCase
from database.models.mpesa_pass_through_outbox import MpesaPassThroughOperationIntent
from database.session import SessionLocal
from services.mpesa_pass_through_monitor import MonitorPolicy, monitor_recovery
from services.mpesa_pass_through_outbox import reserve_operation
from services.mpesa_pass_through_quotes import quote
from services.mpesa_pass_through_store import create_quote_record

ROOT = "/api/v1/admin/mpesa-pass-through"
CLOCK = datetime(2026, 11, 10, 10, 0, tzinfo=timezone.utc)


def seed(db, suffix):
    m = Merchant(name="Monitor " + suffix, slug="monitor-" + suffix)
    db.add(m); db.flush()
    a = Application(merchant_id=m.id, name="Monitor " + suffix, environment="test")
    db.add(a); db.flush()
    q = quote(tenant_id=m.id, direction="outgoing", principal="1000", approved=True)
    tx = create_quote_record(db, merchant_id=m.id, application_id=a.id,
                             idempotency_key="monitor-" + suffix,
                             request={"amount": "1000"}, quote=q)
    intent = reserve_operation(db, merchant_id=m.id, application_id=a.id,
                               transaction_id=tx.id, leg="funding",
                               reference="monitor-" + suffix)
    return m.id, a.id, intent


def test_threshold_validation():
    assert MonitorPolicy().review_after_seconds == 300
    for args in [
        {"review_after_seconds": 29},
        {"review_after_seconds": 3600, "escalate_after_seconds": 3600},
        {"critical_after_seconds": 3600},
        {"critical_after_seconds": 30 * 86400 + 1},
    ]:
        with pytest.raises(ValueError):
            MonitorPolicy(**args)


def test_monitor_classifies_age_and_never_writes():
    with SessionLocal() as db:
        m, a, intent = seed(db, "aged")
        db.flush()
        # Aging a test row without provider execution.
        intent.created_at = CLOCK - timedelta(hours=25)
        db.commit()
    with SessionLocal() as db:
        before = db.scalar(select(func.count(MpesaPassThroughExceptionCase.id)))
        result = monitor_recovery(db, merchant_id=m, application_id=a, now=CLOCK)
        assert result["summary"]["critical"] == 1
        assert result["summary"]["unassigned_or_no_case"] == 1
        assert result["alerts"][0]["recommended_action"] == "manual_review"
        assert result["alerts"][0]["needs_operator_review"] is True
        assert result["read_only"] is True
        assert result["automatic_escalation_enabled"] is False
        assert result["delivery_enabled"] is False
        assert result["live_pass_through_enabled"] is False
        assert db.scalar(select(func.count(MpesaPassThroughExceptionCase.id))) == before
        assert not db.dirty and not db.new


def test_monitor_tenant_isolation():
    with SessionLocal() as db:
        m1, a1, first = seed(db, "first")
        m2, a2, second = seed(db, "second")
        db.flush()
        first.created_at = CLOCK - timedelta(minutes=12)
        second.created_at = CLOCK - timedelta(hours=2)
        db.commit()
    with SessionLocal() as db:
        one = monitor_recovery(db, merchant_id=m1, application_id=a1, now=CLOCK)
        two = monitor_recovery(db, merchant_id=m2, application_id=a2, now=CLOCK)
        assert one["summary"]["review"] == 1
        assert one["summary"]["escalate"] == 0
        assert two["summary"]["escalate"] == 1
        assert len(one["alerts"]) == len(two["alerts"]) == 1
        assert one["alerts"][0]["intent_id"] != two["alerts"][0]["intent_id"]
        assert "reference" not in str(one["alerts"])
        assert "phone" not in str(two["alerts"])


def test_monitor_endpoint_auth_and_policy(client, admin_token):
    url = ROOT + "/recovery/monitor"
    query = {"merchant_id": "a"*36, "application_id": "b"*36}
    # admin_token fixture logs into the shared client and leaves a session cookie.\n    client.cookies.clear()\n    assert client.get(url, params=query).status_code in (401, 403)
    h = {"Authorization": "Bearer " + admin_token}
    bad = client.get(url, params={**query,
        "review_after_seconds": 3600, "escalate_after_seconds": 300}, headers=h)
    assert bad.status_code == 422
    ok = client.get(url, params=query, headers=h)
    assert ok.status_code == 200, ok.text
    assert ok.json()["summary"]["total"] == 0
    assert ok.json()["read_only"] is True
    assert ok.json()["automatic_escalation_enabled"] is False
