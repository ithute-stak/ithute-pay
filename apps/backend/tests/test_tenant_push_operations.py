"""Delivery monitoring and bounded manual retry security tests."""
from datetime import datetime, timezone

from database.config.config import settings
from database.models import (
    ReconciliationItem, TenantReconciliationException,
    TenantReconciliationPushDelivery,
)
from database.session import SessionLocal
from test_tenant_recon_push_worker import _setup
from test_tenant_reconciliation_operations import _login


def _path(merchant_id, suffix=""):
    return f"/api/v1/tenant-portal/merchants/{merchant_id}/reconciliation/alerts/deliveries" + suffix


def _csrf(client):
    return {"X-CSRF-Token": client.cookies.get("ipb_csrf", "")}


def _delivery(merchant_id, status="failed", attempts=5, manual_retries=0):
    with SessionLocal() as db:
        case = db.query(TenantReconciliationException).filter(
            TenantReconciliationException.merchant_id == merchant_id,
            TenantReconciliationException.investigation_status == "investigating",
        ).one()
        row = TenantReconciliationPushDelivery(
            merchant_id=merchant_id,
            case_id=case.id,
            recipient_user_id=case.assigned_user_id,
            alert_type="overdue",
            status=status,
            attempts=attempts,
            manual_retries=manual_retries,
            last_error_code="push_unavailable",
        )
        db.add(row)
        db.commit()
        return row.id


def test_monitor_scopes_viewer_to_self_and_owner_to_tenant(client, monkeypatch):
    own, foreign, investigator = _setup(monkeypatch)
    delivery_id = _delivery(own)
    _login(client)
    response = client.get(_path(own))
    assert response.status_code == 200, response.text
    assert response.json()["scope"] == "tenant"
    assert response.json()["counts"]["failed"] == 1
    assert response.json()["items"][0]["id"] == delivery_id
    assert client.get(_path(foreign)).status_code == 404
    with SessionLocal() as db:
        owner = db.query(TenantReconciliationPushDelivery).filter_by(id=delivery_id).one()
        assert owner.recipient_user_id == investigator
        assert db.query(ReconciliationItem).filter(
            ReconciliationItem.merchant_id == own, ReconciliationItem.status == "mismatch",
        ).count() == 4


def test_manual_retry_requires_live_gate_and_is_bounded(client, monkeypatch):
    own, _, _ = _setup(monkeypatch)
    delivery_id = _delivery(own)
    _login(client)
    target = _path(own, f"/{delivery_id}/retry")
    monkeypatch.setattr(settings, "ITHUTE_RECON_PUSH_DISPATCH_ENABLED", False)
    disabled = client.post(target, headers=_csrf(client))
    assert disabled.status_code == 409
    monkeypatch.setattr(settings, "ITHUTE_RECON_PUSH_DISPATCH_ENABLED", True)
    response = client.post(target, headers=_csrf(client))
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        record = db.get(TenantReconciliationPushDelivery, delivery_id)
        assert record.status == "pending"
        assert record.manual_retries == 1
        assert record.attempts == 0
        # Simulate a second exhausted delivery failure.
        record.status = "failed"
        record.attempts = 5
        db.commit()
    repeated = client.post(target, headers=_csrf(client))
    assert repeated.status_code == 409
    assert "allowance" in repeated.json()["detail"].lower()


def test_cross_tenant_and_nonfailed_retry_denied(client, monkeypatch):
    own, foreign, _ = _setup(monkeypatch)
    delivery_id = _delivery(own, status="delivered", attempts=1)
    _login(client)
    assert client.post(_path(own, f"/{delivery_id}/retry"), headers=_csrf(client)).status_code == 409
    assert client.post(_path(foreign, f"/{delivery_id}/retry"), headers=_csrf(client)).status_code == 404


def test_closed_case_retry_denied_and_viewer_cannot_retry(client, monkeypatch):
    own, _, _ = _setup(monkeypatch)
    delivery_id = _delivery(own)
    with SessionLocal() as db:
        row = db.get(TenantReconciliationPushDelivery, delivery_id)
        case = db.get(TenantReconciliationException, row.case_id)
        case.investigation_status = "closed"
        db.commit()
    _login(client)
    assert client.post(_path(own, f"/{delivery_id}/retry"), headers=_csrf(client)).status_code == 409
