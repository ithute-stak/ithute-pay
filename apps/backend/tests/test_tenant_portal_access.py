"""Human tenant portal access tests. Never use merchant API secrets in browsers."""
from database.models import (
    Merchant, MerchantCommercialAgreement, TenantMerchantContract,
    TenantProviderAccount, TenantUserMembership, User,
)
from database.session import SessionLocal
from core.security import hash_password


def _setup():
    with SessionLocal() as db:
        master = Merchant(name="Master", slug="tenant-portal-master")
        a = Merchant(name="Merchant A", slug="tenant-portal-a")
        b = Merchant(name="Merchant B", slug="tenant-portal-b")
        db.add_all((master, a, b))
        db.flush()
        for merchant in (a, b):
            db.add(TenantMerchantContract(
                master_merchant_id=master.id, tenant_merchant_id=merchant.id,
                status="approved", kyc_status="verified", custody_mode="own_shortcode",
            ))
        db.add(TenantProviderAccount(
            merchant_id=a.id, provider="mpesa", environment="production",
            shortcode="123456", ownership_status="verified", enabled=False,
        ))
        db.add(MerchantCommercialAgreement(
            merchant_id=a.id, version=1, status="approved",
            inbound_fixed_fee="1.00",
        ))
        user = User(
            email="shop-operator@example.com", full_name="Shop Operator",
            password_hash=hash_password("Password123!"), role="merchant_user",
        )
        db.add(user)
        db.commit()
        return a.id, b.id, user.id


def _login_as_tenant(client):
    client.cookies.clear()
    result = client.post("/api/v1/auth/login", json={
        "email": "shop-operator@example.com", "password": "Password123!",
    })
    assert result.status_code == 200, result.text


def test_authenticated_tenant_cannot_read_other_merchants(client, admin_token):
    a, b, user_id = _setup()
    headers = {"Authorization": f"Bearer {admin_token}"}
    grant = client.post("/api/v1/admin/tenant-access/memberships", headers=headers,
                        json={"user_id": user_id, "merchant_id": a, "role": "viewer"})
    assert grant.status_code == 201, grant.text
    _login_as_tenant(client)
    merchants = client.get("/api/v1/tenant-portal/merchants")
    assert merchants.status_code == 200, merchants.text
    assert [r["merchant_id"] for r in merchants.json()] == [a]
    own = client.get(f"/api/v1/tenant-portal/merchants/{a}/overview")
    assert own.status_code == 200, own.text
    assert own.json()["shortcodes"][0]["shortcode"] == "123456"
    assert own.json()["agreement"]["inbound_fixed_fee"] == "1.00"
    assert own.json()["payments_enabled_by_tenant_portal"] is False
    assert client.get(f"/api/v1/tenant-portal/merchants/{b}/overview").status_code == 404
    assert client.post("/api/v1/admin/tenant-access/memberships", json={
        "user_id": user_id, "merchant_id": b, "role": "owner",
    }, headers={"X-CSRF-Token": client.cookies.get("ipb_csrf", "")}).status_code == 403


def test_member_suspension_revokes_tenant_portal_access(client, admin_token):
    a, _, user_id = _setup()
    headers = {"Authorization": f"Bearer {admin_token}"}
    grant = client.post("/api/v1/admin/tenant-access/memberships", headers=headers,
                        json={"user_id": user_id, "merchant_id": a})
    assert grant.status_code == 201
    suspend = client.post(
        f"/api/v1/admin/tenant-access/memberships/{grant.json()['id']}/suspend",
        headers=headers,
    )
    assert suspend.status_code == 200
    _login_as_tenant(client)
    assert client.get("/api/v1/tenant-portal/merchants").json() == []
    assert client.get(f"/api/v1/tenant-portal/merchants/{a}/overview").status_code == 404


def test_unassigned_logged_in_user_cannot_open_tenant_overview(client):
    a, _, _ = _setup()
    _login_as_tenant(client)
    assert client.get(f"/api/v1/tenant-portal/merchants/{a}/overview").status_code == 404


def test_membership_must_reference_approved_tenant(client, admin_token):
    a, b, user_id = _setup()
    with SessionLocal() as db:
        contract = db.query(TenantMerchantContract).filter(
            TenantMerchantContract.tenant_merchant_id == b,
        ).one()
        contract.status = "suspended"
        db.commit()
    response = client.post("/api/v1/admin/tenant-access/memberships",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"user_id": user_id, "merchant_id": b, "role": "viewer"})
    assert response.status_code == 409
    with SessionLocal() as db:
        assert db.query(TenantUserMembership).count() == 0
