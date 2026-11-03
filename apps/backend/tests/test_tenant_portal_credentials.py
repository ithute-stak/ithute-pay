"""Tenant credential tests: no cross-tenant secrets or live activation."""
from database.models import ApiKey, Application, Merchant, TenantMerchantContract, TenantUserMembership, User
from database.session import SessionLocal
from core.security import hash_password, sha256_text


def _seed(role="owner", environment="test"):
    with SessionLocal() as db:
        master = Merchant(name="Ithute", slug="key-master")
        a = Merchant(name="Tenant A", slug="key-tenant-a")
        b = Merchant(name="Tenant B", slug="key-tenant-b")
        db.add_all((master, a, b))
        db.flush()
        for merchant in (a, b):
            db.add(TenantMerchantContract(
                master_merchant_id=master.id, tenant_merchant_id=merchant.id,
                custody_mode="own_shortcode", status="approved", kyc_status="verified",
            ))
        user = User(email="credentials@example.com", full_name="Credentials",
                    role="merchant_user", password_hash=hash_password("Password123!"))
        db.add(user)
        db.flush()
        db.add(TenantUserMembership(user_id=user.id, merchant_id=a.id,
                                     role=role, status="active"))
        own_app = Application(merchant_id=a.id, name="POS A",
                              environment=environment, status="inactive")
        other_app = Application(merchant_id=b.id, name="POS B",
                                environment="test", status="inactive")
        db.add_all((own_app, other_app))
        db.commit()
        return a.id, b.id, own_app.id, other_app.id


def _login(client):
    response = client.post("/api/v1/auth/login", json={
        "email": "credentials@example.com", "password": "Password123!",
    })
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": client.cookies.get("ipb_csrf", "")}


def _base(merchant, app):
    return f"/api/v1/tenant-portal/merchants/{merchant}/applications/{app}"


def test_test_key_is_once_only_scoped_and_inert(client):
    merchant, _, app, _ = _seed()
    headers = _login(client)
    base = _base(merchant, app)
    created = client.post(base + "/test-credentials", headers=headers, json={
        "name": "Read-only diagnostics", "scopes": ["events:read"],
    })
    assert created.status_code == 201, created.text
    secret = created.json()["secret"]
    assert secret.startswith("ipb_test_")
    assert created.json()["usable"] is False
    listed = client.get(base + "/credentials")
    assert listed.status_code == 200, listed.text
    assert len(listed.json()) == 1
    assert "secret" not in listed.json()[0]
    assert secret not in listed.text
    with SessionLocal() as db:
        row = db.query(ApiKey).one()
        assert row.secret_hash == sha256_text(secret)
        assert row.scopes == ["events:read"]
        assert db.get(Application, app).status == "inactive"


def test_reject_empty_wildcard_or_payment_scope(client):
    merchant, _, app, _ = _seed()
    headers = _login(client)
    url = _base(merchant, app) + "/test-credentials"
    for scopes in ([], ["*"], ["payments:create"], ["events:read", "events:read"]):
        result = client.post(url, headers=headers, json={"name": "Test", "scopes": scopes})
        assert result.status_code == 422, result.text


def test_live_app_cannot_issue_tenant_test_credentials(client):
    merchant, _, app, _ = _seed(environment="live")
    headers = _login(client)
    result = client.post(_base(merchant, app) + "/test-credentials",
                         headers=headers, json={"name": "Test", "scopes": ["events:read"]})
    assert result.status_code == 409


def test_viewer_cannot_issue_or_list_keys(client):
    merchant, _, app, _ = _seed(role="viewer")
    headers = _login(client)
    base = _base(merchant, app)
    assert client.get(base + "/credentials").status_code == 403
    assert client.post(base + "/test-credentials", headers=headers, json={
        "name": "Test", "scopes": ["events:read"]}).status_code == 403


def test_cross_tenant_key_operations_are_hidden(client):
    merchant, other, app, foreign_app = _seed()
    headers = _login(client)
    foreign = _base(other, foreign_app)
    own_wrong = _base(merchant, foreign_app)
    assert client.get(foreign + "/credentials").status_code == 404
    assert client.post(foreign + "/test-credentials", headers=headers, json={
        "name": "Test", "scopes": ["events:read"]}).status_code == 404
    assert client.get(own_wrong + "/credentials").status_code == 404


def test_revocation_is_persistent_and_idempotent(client):
    merchant, _, app, _ = _seed()
    headers = _login(client)
    base = _base(merchant, app)
    created = client.post(base + "/test-credentials", headers=headers, json={
        "name": "Test", "scopes": ["events:read"]})
    assert created.status_code == 201, created.text
    key_id = created.json()["id"]
    path = base + f"/credentials/{key_id}/revoke"
    assert client.post(path, headers=headers).json()["revoked"] is True
    assert client.post(path, headers=headers).json()["revoked"] is True
    assert client.get(base + "/credentials").json()[0]["revoked"] is True


def test_rotation_replaces_old_key_without_activating_app(client):
    merchant, _, app, _ = _seed()
    headers = _login(client)
    base = _base(merchant, app)
    first = client.post(base + "/test-credentials", headers=headers, json={
        "name": "Diagnostics", "scopes": ["events:read"], "validity_days": 7,
    })
    assert first.status_code == 201, first.text
    first_id = first.json()["id"]
    assert first.json()["expires_at"] is not None
    rotated = client.post(base + f"/credentials/{first_id}/rotate", headers=headers)
    assert rotated.status_code == 201, rotated.text
    assert rotated.json()["replaced_key_id"] == first_id
    assert rotated.json()["secret"] != first.json()["secret"]
    assert rotated.json()["usable"] is False
    assert client.post(base + f"/credentials/{first_id}/rotate", headers=headers).status_code == 409
    with SessionLocal() as db:
        assert db.get(ApiKey, first_id).revoked_at is not None
        assert db.get(ApiKey, rotated.json()["id"]).revoked_at is None
        assert db.get(Application, app).status == "inactive"


def test_rotation_refuses_foreign_key(client):
    merchant, other, app, foreign_app = _seed()
    with SessionLocal() as db:
        key = ApiKey(application_id=foreign_app, name="Foreign", prefix="ipb_test_foreign",
                     secret_hash="0" * 64, last4="0000", scopes=["events:read"])
        db.add(key)
        db.commit()
        key_id = key.id
    headers = _login(client)
    response = client.post(_base(merchant, app) + f"/credentials/{key_id}/rotate", headers=headers)
    assert response.status_code == 404


def test_test_key_expiration_is_bounded(client):
    merchant, _, app, _ = _seed()
    headers = _login(client)
    url = _base(merchant, app) + "/test-credentials"
    for duration in (0, 91):
        response = client.post(url, headers=headers, json={
            "name": "Invalid duration", "scopes": ["events:read"],
            "validity_days": duration,
        })
        assert response.status_code == 422
