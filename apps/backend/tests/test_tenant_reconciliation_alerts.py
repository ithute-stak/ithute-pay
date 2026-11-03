"""Tenant reconciliation alert isolation, acknowledgement and policy tests."""
from database.models import (
    ReconciliationItem, TenantReconciliationAlertAcknowledgement,
    TenantReconciliationAlertPolicy, TenantReconciliationException,
    TenantUserMembership, User,
)
from database.session import SessionLocal
from test_tenant_reconciliation_operations import _seed, _login


def _path(merchant_id, suffix=""):
    return f"/api/v1/tenant-portal/merchants/{merchant_id}/reconciliation/alerts" + suffix


def _csrf(client):
    return {"X-CSRF-Token": client.cookies.get("ipb_csrf", "")}


def test_viewer_receives_scoped_in_app_alerts_but_cannot_change_settings(client):
    own, foreign, _ = _seed(role="viewer")
    _login(client)
    result = client.get(_path(own))
    assert result.status_code == 200, result.text
    payload = result.json()
    assert payload["delivery"] == "in_app_on_demand"
    assert payload["unacknowledged_count"] == 3
    assert {row["alert_type"] for row in payload["alerts"]} == {"overdue", "unassigned", "escalated"}
    assert client.get(_path(foreign)).status_code == 404
    assert client.put(_path(own, "/settings"), headers=_csrf(client), json={
        "overdue_after_days": 10, "unassigned_after_days": 3,
    }).status_code == 403


def test_owner_can_configure_thresholds_for_only_their_tenant(client):
    own, foreign, _ = _seed(role="owner")
    _login(client)
    settings = {
        "overdue_after_days": 14, "unassigned_after_days": 7,
        "overdue_enabled": True, "unassigned_enabled": False,
        "escalated_enabled": True,
    }
    result = client.put(_path(own, "/settings"), headers=_csrf(client), json=settings)
    assert result.status_code == 200, result.text
    assert result.json() == settings
    assert client.get(_path(own, "/settings")).json() == settings
    # Only the explicitly escalated case remains visible at the longer threshold.
    alerts = client.get(_path(own)).json()
    assert alerts["unacknowledged_count"] == 1
    assert alerts["alerts"][0]["alert_type"] == "escalated"
    assert client.put(_path(foreign, "/settings"), headers=_csrf(client),
                      json=settings).status_code == 404
    assert client.put(_path(own, "/settings"), headers=_csrf(client), json={
        **settings, "overdue_after_days": 0,
    }).status_code == 422


def test_alert_acknowledgement_is_idempotent_and_not_financial_state(client):
    own, _, _ = _seed(role="viewer")
    _login(client)
    data = client.get(_path(own)).json()["alerts"]
    overdue = next(row for row in data if row["alert_type"] == "overdue")
    url = _path(own, f"/{overdue['case_id']}/overdue/acknowledge")
    first = client.post(url, headers=_csrf(client))
    assert first.status_code == 200, first.text
    second = client.post(url, headers=_csrf(client))
    assert second.status_code == 200
    assert client.get(_path(own)).json()["unacknowledged_count"] == 2
    history = client.get(_path(own), params={"include_acknowledged": True}).json()
    assert any(item["acknowledged"] for item in history["alerts"])
    with SessionLocal() as db:
        assert db.query(TenantReconciliationAlertAcknowledgement).count() == 1
        assert db.query(ReconciliationItem).filter(
            ReconciliationItem.merchant_id == own, ReconciliationItem.status == "mismatch",
        ).count() == 4
        assert db.query(TenantReconciliationException).filter(
            TenantReconciliationException.merchant_id == own,
            TenantReconciliationException.investigation_status == "closed",
        ).count() == 1


def test_cannot_acknowledge_foreign_case_or_inactive_alert(client):
    own, foreign, _ = _seed()
    _login(client)
    with SessionLocal() as db:
        foreign_case = db.query(TenantReconciliationException).filter(
            TenantReconciliationException.merchant_id == foreign,
        ).one()
        foreign_id = foreign_case.id
        closed_case = db.query(TenantReconciliationException).filter(
            TenantReconciliationException.merchant_id == own,
            TenantReconciliationException.investigation_status == "closed",
        ).one()
        closed_id = closed_case.id
    assert client.post(_path(own, f"/{foreign_id}/escalated/acknowledge"),
                       headers=_csrf(client)).status_code == 404
    assert client.post(_path(own, f"/{closed_id}/overdue/acknowledge"),
                       headers=_csrf(client)).status_code == 404


def test_alerts_require_authentication(client):
    own, _, _ = _seed()
    assert client.get(_path(own)).status_code == 401
    assert client.get(_path(own, "/settings")).status_code == 401
