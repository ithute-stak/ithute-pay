"""Phase 15 HTTP safety: scoped operator notices and read-only alert counters."""
from database.models import Application, Merchant, User
from database.session import SessionLocal
from core.security import hash_password
from services.mpesa_pass_through_outbox import reserve_operation
from services.mpesa_pass_through_quotes import quote
from services.mpesa_pass_through_store import create_quote_record

ROOT = "/api/v1/admin/mpesa-pass-through"


def seed_case(client, admin_token, suffix):
    with SessionLocal() as db:
        merchant = Merchant(name="Alert " + suffix, slug="alert-" + suffix)
        db.add(merchant); db.flush()
        app = Application(merchant_id=merchant.id, name="Alert " + suffix, environment="test")
        recipient = User(email="alert-" + suffix + "@example.com",
                         password_hash="no-login", role="platform_admin", is_active=True)
        db.add_all([app, recipient]); db.flush()
        q = quote(tenant_id=merchant.id, direction="outgoing", principal="1000", approved=True)
        tx = create_quote_record(db, merchant_id=merchant.id, application_id=app.id,
                                 idempotency_key="alert-" + suffix,
                                 request={"amount": "1000"}, quote=q)
        intent = reserve_operation(db, merchant_id=merchant.id, application_id=app.id,
                                   transaction_id=tx.id, leg="funding", reference="alert-" + suffix)
        m, a, i, recipient_id = merchant.id, app.id, intent.id, recipient.id
        db.commit()
    response = client.post(ROOT + "/cases",
        headers={"Authorization": "Bearer " + admin_token},
        json={"merchant_id": m, "application_id": a, "intent_id": i,
              "classification": "provider_unconfirmed"})
    assert response.status_code == 201, response.text
    return m, a, response.json()["id"], recipient_id


def test_notices_require_authentication(client):
    for url in [ROOT + "/alerts/summary", ROOT + "/cases/" + "a"*36 + "/notices"]:
        assert client.get(url).status_code in (401, 403, 422)
    assert client.post(ROOT + "/cases/" + "a"*36 + "/notices", json={}).status_code in (401, 403, 422)
    assert client.post(ROOT + "/notices/" + "a"*36 + "/cancel", json={}).status_code in (401, 403, 422)


def test_prepare_list_cancel_and_summary_are_idempotent(client, admin_token):
    m, a, case, recipient = seed_case(client, admin_token, "normal")
    headers = {"Authorization": "Bearer " + admin_token}
    payload = {"merchant_id": m, "application_id": a, "recipient_user_id": recipient}
    url = ROOT + "/cases/" + case + "/notices"
    first = client.post(url, headers=headers, json=payload)
    assert first.status_code == 201, first.text
    again = client.post(url, headers=headers, json=payload)
    assert again.status_code == 201, again.text
    assert first.json()["id"] == again.json()["id"]
    assert first.json()["delivery_enabled"] is False
    assert "phone" not in first.text.lower() and "body" not in first.text.lower()
    params = {"merchant_id": m, "application_id": a}
    listed = client.get(url, headers=headers, params=params)
    assert listed.status_code == 200 and len(listed.json()) == 1
    summary = client.get(ROOT + "/alerts/summary", headers=headers, params=params)
    assert summary.status_code == 200, summary.text
    assert summary.json()["cases"]["open"] == 1
    assert summary.json()["notices"]["prepared"] == 1
    assert summary.json()["delivery_enabled"] is False
    cancel_url = ROOT + "/notices/" + first.json()["id"] + "/cancel"
    cancelled = client.post(cancel_url, headers=headers, json=params)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    second_cancel = client.post(cancel_url, headers=headers, json=params)
    assert second_cancel.status_code == 200
    assert second_cancel.json()["id"] == cancelled.json()["id"]
    summary = client.get(ROOT + "/alerts/summary", headers=headers, params=params).json()
    assert summary["notices"] == {"prepared": 0, "cancelled": 1}


def test_cross_scope_is_hidden_and_summary_is_isolated(client, admin_token):
    m1, a1, case1, receiver1 = seed_case(client, admin_token, "scope-a")
    m2, a2, _, _ = seed_case(client, admin_token, "scope-b")
    h = {"Authorization": "Bearer " + admin_token}
    url = ROOT + "/cases/" + case1 + "/notices"
    assert client.post(url, headers=h, json={
        "merchant_id": m2, "application_id": a2,
        "recipient_user_id": receiver1,
    }).status_code == 409
    assert client.get(url, headers=h, params={
        "merchant_id": m2, "application_id": a2,
    }).status_code == 404
    result = client.get(ROOT + "/alerts/summary", headers=h,
        params={"merchant_id": m2, "application_id": a2})
    assert result.status_code == 200
    assert result.json()["notices"]["prepared"] == 0
    assert result.json()["cases"]["open"] == 1


def test_non_platform_user_cannot_access_notices(client):
    with SessionLocal() as db:
        user = User(email="limited-alert@example.com", password_hash=hash_password("Password123!"),
                    role="merchant_admin", is_active=True)
        db.add(user); db.commit()
    login = client.post("/api/v1/auth/login",
        json={"email": "limited-alert@example.com", "password": "Password123!"})
    assert login.status_code == 200
    h = {"Authorization": "Bearer " + login.json()["access_token"]}
    assert client.get(ROOT + "/alerts/summary", headers=h,
        params={"merchant_id": "a"*36, "application_id": "b"*36}).status_code == 403
    assert client.post(ROOT + "/cases/" + "a"*36 + "/notices", headers=h,
        json={"merchant_id": "a"*36, "application_id": "b"*36,
              "recipient_user_id": "c"*36}).status_code == 403
