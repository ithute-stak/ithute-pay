"""Tenant portal shortcode request authorization and safe activation tests."""
from database.models import Merchant, TenantMerchantContract, TenantProviderAccount, TenantUserMembership, User
from database.session import SessionLocal
from core.security import hash_password


def _seed(role="owner", custody="own_shortcode"):
    with SessionLocal() as db:
        master = Merchant(name="Ithute", slug="portal-shortcode-master")
        own = Merchant(name="My Shop", slug="portal-shortcode-shop")
        other = Merchant(name="Other Shop", slug="portal-shortcode-other")
        db.add_all([master, own, other])
        db.flush()
        for merchant in (own, other):
            db.add(TenantMerchantContract(
                master_merchant_id=master.id,
                tenant_merchant_id=merchant.id,
                status="approved", kyc_status="verified",
                custody_mode=custody if merchant.id == own.id else "own_shortcode",
            ))
        user = User(
            email="shortcode-owner@example.com", full_name="Shortcode Owner",
            password_hash=hash_password("Password123!"), role="merchant_user",
        )
        db.add(user)
        db.flush()
        db.add(TenantUserMembership(
            user_id=user.id, merchant_id=own.id, role=role, status="active",
        ))
        db.commit()
        return own.id, other.id


def _login(client):
    result = client.post("/api/v1/auth/login", json={
        "email": "shortcode-owner@example.com", "password": "Password123!",
    })
    assert result.status_code == 200, result.text
    return {"X-CSRF-Token": client.cookies.get("ipb_csrf", "")}


def test_owner_requests_shortcode_without_activation(client):
    own, _ = _seed()
    headers = _login(client)
    response = client.post(
        f"/api/v1/tenant-portal/merchants/{own}/shortcode-requests",
        json={"provider": "mpesa", "environment": "sandbox", "shortcode": "1234567"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["ownership_status"] == "pending"
    assert response.json()["enabled"] is False
    with SessionLocal() as db:
        account = db.query(TenantProviderAccount).one()
        assert account.merchant_id == own
        assert account.enabled is False


def test_viewer_cannot_submit_shortcode(client):
    own, _ = _seed(role="viewer")
    headers = _login(client)
    response = client.post(
        f"/api/v1/tenant-portal/merchants/{own}/shortcode-requests",
        json={"shortcode": "1234567"}, headers=headers,
    )
    assert response.status_code == 403


def test_tenant_cannot_submit_for_other_business(client):
    _, other = _seed()
    headers = _login(client)
    response = client.post(
        f"/api/v1/tenant-portal/merchants/{other}/shortcode-requests",
        json={"shortcode": "1234567"}, headers=headers,
    )
    assert response.status_code == 404


def test_shared_custody_request_cannot_be_made_through_shortcode_portal(client):
    own, _ = _seed(custody="master_shortcode")
    headers = _login(client)
    response = client.post(
        f"/api/v1/tenant-portal/merchants/{own}/shortcode-requests",
        json={"shortcode": "1234567"}, headers=headers,
    )
    assert response.status_code == 403


def test_duplicate_shortcode_rejected(client):
    own, _ = _seed()
    headers = _login(client)
    url = f"/api/v1/tenant-portal/merchants/{own}/shortcode-requests"
    payload = {"shortcode": "1234567"}
    assert client.post(url, json=payload, headers=headers).status_code == 201
    assert client.post(url, json=payload, headers=headers).status_code == 409
