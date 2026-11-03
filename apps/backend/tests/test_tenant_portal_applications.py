"""Phase 7: tenant POS application provisioning stays isolated and inactive."""
from database.models import Application, ApiKey, Merchant, TenantMerchantContract, TenantUserMembership, User
from database.session import SessionLocal
from core.security import hash_password, generate_secret, sha256_text


def _seed(role="owner", custody_mode="own_shortcode"):
    with SessionLocal() as db:
        master = Merchant(name="Ithute", slug="app-master")
        own = Merchant(name="Own Shop", slug="app-own")
        other = Merchant(name="Other Shop", slug="app-other")
        db.add_all((master, own, other))
        db.flush()
        for merchant in (own, other):
            db.add(TenantMerchantContract(
                master_merchant_id=master.id, tenant_merchant_id=merchant.id,
                status="approved", kyc_status="verified",
                custody_mode=custody_mode if merchant.id == own.id else "own_shortcode",
            ))
        user = User(email="apps@example.com", full_name="App Tester",
                    password_hash=hash_password("Password123!"), role="merchant_user")
        db.add(user)
        db.flush()
        db.add(TenantUserMembership(user_id=user.id, merchant_id=own.id, role=role, status="active"))
        db.commit()
        return own.id, other.id


def _login(client):
    result = client.post("/api/v1/auth/login", json={
        "email": "apps@example.com", "password": "Password123!",
    })
    assert result.status_code == 200, result.text
    return {"X-CSRF-Token": client.cookies.get("ipb_csrf", "")}


def test_owner_creates_inactive_pos_application(client):
    own, _ = _seed()
    headers = _login(client)
    url = f"/api/v1/tenant-portal/merchants/{own}/applications"
    response = client.post(url, json={"name": "Shop POS", "environment": "test"}, headers=headers)
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "inactive"
    assert response.json()["credentials_issued"] is False
    listed = client.get(url)
    assert listed.status_code == 200
    assert [a["id"] for a in listed.json()] == [response.json()["id"]]
    with SessionLocal() as db:
        row = db.get(Application, response.json()["id"])
        assert row.merchant_id == own
        assert row.status == "inactive"
        assert db.query(ApiKey).count() == 0


def test_no_cross_tenant_application_creation_or_listing(client):
    _, other = _seed()
    headers = _login(client)
    url = f"/api/v1/tenant-portal/merchants/{other}/applications"
    assert client.get(url).status_code == 404
    assert client.post(url, json={"name": "Wrong Shop"}, headers=headers).status_code == 404


def test_viewer_cannot_create_pos_application(client):
    own, _ = _seed(role="viewer")
    headers = _login(client)
    response = client.post(f"/api/v1/tenant-portal/merchants/{own}/applications",
                           json={"name": "POS"}, headers=headers)
    assert response.status_code == 403


def test_master_shortcode_custody_cannot_register_application(client):
    own, _ = _seed(custody_mode="master_shortcode")
    headers = _login(client)
    response = client.post(f"/api/v1/tenant-portal/merchants/{own}/applications",
                           json={"name": "POS"}, headers=headers)
    assert response.status_code == 403


def test_disable_active_app_revokes_all_keys(client):
    own, _ = _seed()
    with SessionLocal() as db:
        app = Application(merchant_id=own, name="Old App",
                          environment="test", status="active")
        db.add(app)
        db.flush()
        secret = generate_secret("ipb_test_", 16)
        key = ApiKey(application_id=app.id, name="Old Key",
                     prefix=secret[:16], last4=secret[-4:],
                     secret_hash=sha256_text(secret), scopes=[])
        db.add(key)
        db.commit()
        app_id, key_id = app.id, key.id
    headers = _login(client)
    response = client.post(
        f"/api/v1/tenant-portal/merchants/{own}/applications/{app_id}/disable",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["keys_revoked"] == 1
    with SessionLocal() as db:
        assert db.get(Application, app_id).status == "inactive"
        assert db.get(ApiKey, key_id).revoked_at is not None


def test_cannot_disable_another_tenants_application(client):
    own, other = _seed()
    with SessionLocal() as db:
        app = Application(merchant_id=other, name="Other POS", status="active")
        db.add(app)
        db.commit()
        app_id = app.id
    headers = _login(client)
    response = client.post(
        f"/api/v1/tenant-portal/merchants/{own}/applications/{app_id}/disable",
        headers=headers,
    )
    assert response.status_code == 404
    with SessionLocal() as db:
        assert db.get(Application, app_id).status == "active"
