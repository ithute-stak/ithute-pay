"""Tenant reconciliation casework security and audit regression tests."""
from datetime import datetime, timezone

from core.security import hash_password
from database.models import (
    Application, Merchant, ReconciliationItem, TenantMerchantContract,
    TenantReconciliationException, TenantReconciliationExceptionEvent,
    TenantUserMembership, User,
)
from database.session import SessionLocal


def _seed(role="finance"):
    with SessionLocal() as db:
        master = Merchant(name="Ithute Master", slug="case-master")
        own = Merchant(name="Case Merchant", slug="case-own")
        foreign = Merchant(name="Foreign Merchant", slug="case-foreign")
        db.add_all([master, own, foreign])
        db.flush()
        for merchant in (own, foreign):
            db.add(TenantMerchantContract(
                master_merchant_id=master.id, tenant_merchant_id=merchant.id,
                status="approved", kyc_status="verified", custody_mode="own_shortcode",
            ))
        user = User(email="cases@example.com", full_name="Case Investigator",
                    password_hash=hash_password("Password123!"), role="merchant_user")
        db.add(user)
        db.flush()
        db.add(TenantUserMembership(user_id=user.id, merchant_id=own.id,
                                    status="active", role=role))
        own_item = ReconciliationItem(
            merchant_id=own.id, provider="mpesa", status="mismatch",
            reconciliation_date=datetime.now(timezone.utc).date(),
            expected_amount="100.00", provider_amount="95.00", currency="LSL",
        )
        other_item = ReconciliationItem(
            merchant_id=foreign.id, provider="mpesa", status="mismatch",
            reconciliation_date=datetime.now(timezone.utc).date(),
            expected_amount="100.00", provider_amount="92.00", currency="LSL",
        )
        db.add_all([own_item, other_item])
        db.commit()
        return own.id, foreign.id, own_item.id, other_item.id, user.id


def _login(client):
    response = client.post("/api/v1/auth/login", json={
        "email": "cases@example.com", "password": "Password123!",
    })
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": client.cookies.get("ipb_csrf", "")}


def _base(merchant):
    return f"/api/v1/tenant-portal/merchants/{merchant}/reconciliation"


def _payload(status="open", assigned=None, evidence=None):
    return {
        "classification": "amount_mismatch",
        "investigation_status": status,
        "assigned_user_id": assigned,
        "evidence_reference": evidence,
        "notes": "Investigate provider statement",
    }


def test_create_update_and_history_do_not_mutate_financial_state(client):
    own, _, item, _, user_id = _seed()
    headers = _login(client)
    created = client.post(_base(own) + f"/items/{item}/exception", headers=headers,
                          json=_payload(assigned=user_id))
    assert created.status_code == 201, created.text
    case_id = created.json()["id"]
    assert created.json()["investigation_status"] == "open"
    updated = client.patch(_base(own) + f"/exceptions/{case_id}", headers=headers,
                           json=_payload("closed", assigned=user_id, evidence="provider-case-001"))
    assert updated.status_code == 200, updated.text
    history = client.get(_base(own) + f"/exceptions/{case_id}/history")
    assert history.status_code == 200, history.text
    assert [event["action"] for event in history.json()] == ["created", "updated"]
    assert history.json()[1]["detail"]["before"]["investigation_status"] == "open"
    assert client.patch(_base(own) + f"/exceptions/{case_id}", headers=headers,
                        json=_payload("investigating")).status_code == 409
    with SessionLocal() as db:
        row = db.get(ReconciliationItem, item)
        assert row.status == "mismatch"
        assert str(row.expected_amount) == "100.00"
        assert str(row.provider_amount) == "95.00"
        assert db.query(TenantReconciliationException).count() == 1
        assert db.query(TenantReconciliationExceptionEvent).count() == 2


def test_viewer_cannot_create_investigation(client):
    own, _, item, _, _ = _seed(role="viewer")
    headers = _login(client)
    result = client.post(_base(own) + f"/items/{item}/exception",
                         headers=headers, json=_payload())
    assert result.status_code == 403
    assert client.get(_base(own) + "/exceptions").status_code == 200


def test_foreign_item_and_foreign_merchant_are_hidden(client):
    own, foreign, _, foreign_item, _ = _seed()
    headers = _login(client)
    assert client.post(_base(own) + f"/items/{foreign_item}/exception",
                       headers=headers, json=_payload()).status_code == 404
    assert client.get(_base(foreign) + "/exceptions").status_code == 404


def test_duplicate_case_and_invalid_assignment_are_rejected(client):
    own, _, item, _, _ = _seed()
    headers = _login(client)
    url = _base(own) + f"/items/{item}/exception"
    assert client.post(url, headers=headers, json=_payload()).status_code == 201
    assert client.post(url, headers=headers, json=_payload()).status_code == 409
    with SessionLocal() as db:
        assert db.query(TenantReconciliationException).count() == 1
    another = client.post(url, headers=headers,
                          json=_payload(assigned="00000000-0000-0000-0000-000000000000"))
    assert another.status_code == 422


def test_closed_case_requires_evidence(client):
    own, _, item, _, _ = _seed()
    headers = _login(client)
    created = client.post(_base(own) + f"/items/{item}/exception",
                          headers=headers, json=_payload())
    case_id = created.json()["id"]
    result = client.patch(_base(own) + f"/exceptions/{case_id}",
                          headers=headers, json=_payload("closed"))
    assert result.status_code == 422
