"""Phase 17 durable, scoped snapshots and acknowledgement regression."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from database.models import Application, AuditLog, Merchant, User
from database.models.mpesa_pt_monitor_history import MpesaPtMonitorRun, MpesaPtMonitorAlert
from database.session import SessionLocal
from services.mpesa_pt_monitor_history import (
    capture_monitor_snapshot, acknowledge_monitor_alert, list_monitor_alerts,
    list_monitor_runs,
)
from services.mpesa_pass_through_lifecycle import TransactionError
from services.mpesa_pass_through_outbox import reserve_operation
from services.mpesa_pass_through_quotes import quote
from services.mpesa_pass_through_store import create_quote_record

NOW = datetime(2026, 11, 10, 12, 20, tzinfo=timezone.utc)
BUCKET = "2026-11-10T12:00Z"
ROOT = "/api/v1/admin/mpesa-pass-through"


def seed(db, suffix):
    m = Merchant(name="History " + suffix, slug="pt-history-" + suffix)
    db.add(m); db.flush()
    a = Application(merchant_id=m.id, name="History", environment="test")
    u = User(email="pt-history-" + suffix + "@example.com",
             password_hash="no-login", role="platform_super_admin", is_active=True)
    db.add_all([a, u]); db.flush()
    q = quote(tenant_id=m.id, direction="outgoing", principal="1000", approved=True)
    tx = create_quote_record(db, merchant_id=m.id, application_id=a.id,
                             idempotency_key="history-" + suffix,
                             request={"amount": "1000"}, quote=q)
    intent = reserve_operation(db, merchant_id=m.id, application_id=a.id,
                               transaction_id=tx.id, leg="funding", reference="history-" + suffix)
    db.flush()
    intent.created_at = NOW - timedelta(days=2)
    db.flush()
    return m.id, a.id, u.id, intent.id


def test_hourly_idempotency_and_acknowledgement_audit():
    with SessionLocal() as db:
        m, a, u, intent = seed(db, "repeat")
        args = dict(merchant_id=m, application_id=a, actor_user_id=u,
                    bucket_utc=BUCKET, now=NOW)
        one = capture_monitor_snapshot(db, **args)
        again = capture_monitor_snapshot(db, **args)
        assert one.id == again.id
        assert one.total == 1 and one.critical_count == 1
        alerts = list_monitor_alerts(db, merchant_id=m, application_id=a)
        assert len(alerts) == 1 and alerts[0].intent_id == intent
        alert_id = alerts[0].id
        ack = acknowledge_monitor_alert(db, merchant_id=m, application_id=a,
                                        actor_user_id=u, alert_id=alert_id)
        again_ack = acknowledge_monitor_alert(db, merchant_id=m, application_id=a,
                                             actor_user_id=u, alert_id=alert_id)
        assert ack.id == again_ack.id
        assert ack.status == "acknowledged"
        assert db.scalar(select(func.count(AuditLog.id)).where(
            AuditLog.action == "mpesa_pass_through.monitor.acknowledged")) == 1
        db.commit()
    with SessionLocal() as db:
        assert db.scalar(select(func.count(MpesaPtMonitorRun.id))) == 1
        assert db.scalar(select(func.count(MpesaPtMonitorAlert.id))) == 1
        assert len(list_monitor_runs(db, merchant_id=m, application_id=a)) == 1


def test_scopes_admin_and_bucket_are_enforced():
    with SessionLocal() as db:
        m, a, u, _ = seed(db, "scope")
        other_m, other_a, other_u, _ = seed(db, "other")
        with pytest.raises(ValueError):
            capture_monitor_snapshot(db, merchant_id=m, application_id=a,
                                     actor_user_id=u, bucket_utc="2026-11-10T11:00Z", now=NOW)
        with pytest.raises(TransactionError):
            capture_monitor_snapshot(db, merchant_id=m, application_id=a,
                                     actor_user_id="missing", bucket_utc=BUCKET, now=NOW)
        run = capture_monitor_snapshot(db, merchant_id=m, application_id=a,
                                       actor_user_id=u, bucket_utc=BUCKET, now=NOW)
        alert = list_monitor_alerts(db, merchant_id=m, application_id=a)[0]
        with pytest.raises(TransactionError):
            acknowledge_monitor_alert(db, merchant_id=other_m,
                                      application_id=other_a, actor_user_id=other_u,
                                      alert_id=alert.id)
        assert list_monitor_alerts(db, merchant_id=other_m, application_id=other_a) == []
        assert list_monitor_runs(db, merchant_id=other_m, application_id=other_a) == []


def test_http_history_requires_admin(client, admin_token):
    path = ROOT + "/monitoring/history"
    params = {"merchant_id": "a"*36, "application_id": "b"*36}
    client.cookies.clear()
    assert client.get(path, params=params).status_code in (401, 403)
    headers = {"Authorization": "Bearer " + admin_token}
    assert client.get(path, params=params, headers=headers).json() == []
    assert client.get(ROOT + "/monitoring/alerts", params=params, headers=headers).json() == []
    response = client.post(ROOT + "/monitoring/capture", headers=headers, json=params)
    assert response.status_code == 201, response.text
    assert response.json()["delivery_enabled"] is False
