"""HTTP integration tests: administrative investigation only, no payment dispatch."""
from database.models import Application, Merchant, User
from database.session import SessionLocal
from services.mpesa_pass_through_outbox import reserve_operation
from services.mpesa_pass_through_quotes import quote
from services.mpesa_pass_through_store import create_quote_record
from core.security import hash_password

ROOT = "/api/v1/admin/mpesa-pass-through"


def seed_operation(label):
    with SessionLocal() as db:
        m = Merchant(name="Review " + label, slug="pt-api-" + label)
        db.add(m); db.flush()
        app = Application(merchant_id=m.id, name="Review " + label, environment="test")
        db.add(app); db.flush()
        q = quote(tenant_id=m.id, direction="outgoing", principal="1000", approved=True)
        tx = create_quote_record(
            db, merchant_id=m.id, application_id=app.id,
            idempotency_key="review-" + label,
            request={"amount": "1000"}, quote=q,
        )
        intent = reserve_operation(
            db, merchant_id=m.id, application_id=app.id,
            transaction_id=tx.id, leg="funding", reference="review-" + label,
        )
        ids = (m.id, app.id, intent.id)
        db.commit()
        return ids


def auth(token):
    return {"Authorization": "Bearer " + token}


def test_all_operations_require_login(client):
    for path in ["/recovery", "/cases"]:
        assert client.get(ROOT + path).status_code in (401, 403, 422)
    assert client.post(ROOT + "/cases", json={}).status_code in (401, 403, 422)


def test_platform_admin_can_open_review_and_preview_non_sendable_notice(client, admin_token):
    m, app, intent = seed_operation("admin")
    headers = auth(admin_token)
    created = client.post(ROOT + "/cases", headers=headers, json={
        "merchant_id": m, "application_id": app,
        "intent_id": intent, "classification": "provider_unconfirmed",
    })
    assert created.status_code == 201, created.text
    case_id = created.json()["id"]
    assert created.json()["status"] == "open"
    again = client.post(ROOT + "/cases", headers=headers, json={
        "merchant_id": m, "application_id": app,
        "intent_id": intent, "classification": "provider_unconfirmed",
    })
    assert again.status_code == 201
    assert again.json()["id"] == case_id

    listing = client.get(ROOT + "/cases", headers=headers,
                         params={"merchant_id": m, "application_id": app})
    assert listing.status_code == 200
    assert len(listing.json()) == 1
    review = client.post(ROOT + "/cases/" + case_id + "/review",
                         headers=headers, json={"merchant_id": m,
                         "application_id": app, "status": "investigating"})
    assert review.status_code == 200, review.text
    assert review.json()["status"] == "investigating"

    preview = client.get(ROOT + "/cases/" + case_id + "/notification-preview",
                         headers=headers,
                         params={"merchant_id": m, "application_id": app})
    assert preview.status_code == 200, preview.text
    assert preview.json()["safe_to_send"] is False
    assert preview.json()["delivery_enabled"] is False
    assert "under review" in preview.json()["text"]
    assert "successful" not in preview.json()["text"].lower()

    premature = client.post(ROOT + "/cases/" + case_id + "/review",
                            headers=headers, json={"merchant_id": m,
                            "application_id": app, "status": "closed",
                            "evidence_reference": "document-123456"})
    assert premature.status_code == 409


def test_scoped_listing_does_not_expose_other_tenants(client, admin_token):
    m1, a1, intent1 = seed_operation("one")
    m2, a2, intent2 = seed_operation("two")
    for m,a,i in [(m1,a1,intent1),(m2,a2,intent2)]:
        resp = client.post(ROOT + "/cases", headers=auth(admin_token), json={
            "merchant_id": m, "application_id": a, "intent_id": i,
            "classification": "provider_unconfirmed",
        })
        assert resp.status_code == 201, resp.text
    response = client.get(ROOT + "/cases", headers=auth(admin_token),
                          params={"merchant_id": m1, "application_id": a1})
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["merchant_id"] == m1
    foreign = client.get(ROOT + "/cases/" + response.json()[0]["id"] + "/notification-preview",
                         headers=auth(admin_token),
                         params={"merchant_id": m2, "application_id": a2})
    assert foreign.status_code == 404


def test_recovery_endpoint_only_returns_scoped_safe_metadata(client, admin_token):
    m, app, intent = seed_operation("recovery")
    response = client.get(ROOT + "/recovery", headers=auth(admin_token),
                          params={"merchant_id": m, "application_id": app,
                                  "age_seconds": 30})
    assert response.status_code == 200, response.text
    assert response.json()["summary"]["total"] == 0
    assert "provider_secret" not in response.text.lower()
    assert "phone" not in response.text.lower()


def test_merchant_user_is_denied_even_when_logged_in(client):
    with SessionLocal() as db:
        user = User(email="limited-pt-api@example.com", full_name="Limited",
                    password_hash=hash_password("Password123!"),
                    role="merchant_admin")
        db.add(user); db.commit()
    client.cookies.clear()
    response = client.post("/api/v1/auth/login",
                           json={"email":"limited-pt-api@example.com",
                                 "password":"Password123!"})
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    assert client.get(ROOT + "/cases", headers=auth(token),
                      params={"merchant_id": "a"*36,
                              "application_id":"b"*36}).status_code == 403
