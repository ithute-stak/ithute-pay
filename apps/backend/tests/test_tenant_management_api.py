"""Tenant onboarding API contracts: no provider requests or funds movement."""
from database.models import (
    Merchant, Application, ApiKey, TenantMerchantContract, TenantProviderAccount,
    MerchantCommercialAgreement, User,
)
from database.session import SessionLocal
from core.security import generate_secret, sha256_text, hash_password


def _auth_for_tenant(slug):
    secret = generate_secret("ipb_test_", 16)
    with SessionLocal() as db:
        master = db.query(Merchant).filter(Merchant.slug == "master-for-tenancy").first()
        if master is None:
            master = Merchant(name="Ithute Master", slug="master-for-tenancy")
            db.add(master)
            db.flush()
        tenant = Merchant(name=slug, slug=slug)
        db.add(tenant)
        db.flush()
        app = Application(merchant_id=tenant.id, name="POS", environment="test")
        db.add(app)
        db.flush()
        db.add(ApiKey(
            application_id=app.id, name="POS integration", prefix=secret[:16],
            secret_hash=sha256_text(secret), last4=secret[-4:], scopes=[],
        ))
        db.add(TenantMerchantContract(
            master_merchant_id=master.id,
            tenant_merchant_id=tenant.id, custody_mode="own_shortcode",
        ))
        db.commit()
        return tenant.id, secret


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_shortcodes_are_tenant_scoped_and_unverified(client):
    tenant_a, key_a = _auth_for_tenant("tenant-api-a")
    tenant_b, key_b = _auth_for_tenant("tenant-api-b")
    response = client.post(
        "/api/v1/merchant/tenancy/shortcodes", headers=_headers(key_a),
        json={"provider": "mpesa", "environment": "production", "shortcode": "123456"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["ownership_status"] == "pending"
    assert response.json()["enabled"] is False
    assert len(client.get("/api/v1/merchant/tenancy/shortcodes", headers=_headers(key_a)).json()) == 1
    assert client.get("/api/v1/merchant/tenancy/shortcodes", headers=_headers(key_b)).json() == []
    duplicated = client.post(
        "/api/v1/merchant/tenancy/shortcodes", headers=_headers(key_b),
        json={"provider": "mpesa", "environment": "production", "shortcode": "123456"},
    )
    assert duplicated.status_code == 409
    assert "owner" not in duplicated.text.lower()
    with SessionLocal() as db:
        rows = db.query(TenantProviderAccount).all()
        assert len(rows) == 1
        assert rows[0].merchant_id == tenant_a
        assert rows[0].merchant_id != tenant_b


def test_shortcode_request_requires_tenant_contract(client, merchant_api_key):
    response = client.post(
        "/api/v1/merchant/tenancy/shortcodes",
        headers=_headers(merchant_api_key),
        json={"provider": "mpesa", "shortcode": "555555"},
    )
    assert response.status_code == 403


def test_shortcode_request_rejects_invalid_provider_and_shortcodes(client):
    _, key = _auth_for_tenant("tenant-invalid")
    bad = client.post(
        "/api/v1/merchant/tenancy/shortcodes", headers=_headers(key),
        json={"provider": "golink", "shortcode": "abcDEF"},
    )
    assert bad.status_code == 422


def test_merchant_sees_only_approved_own_agreement(client):
    tenant_a, key_a = _auth_for_tenant("tenant-fees-a")
    _, key_b = _auth_for_tenant("tenant-fees-b")
    with SessionLocal() as db:
        db.add(MerchantCommercialAgreement(
            merchant_id=tenant_a, version=1, status="approved",
            inbound_fixed_fee="1.20", outbound_fixed_fee="2.10",
        ))
        db.commit()
    first = client.get("/api/v1/merchant/tenancy/agreement", headers=_headers(key_a))
    assert first.status_code == 200
    assert first.json()["inbound_fixed_fee"] == "1.20"
    assert client.get(
        "/api/v1/merchant/tenancy/agreement", headers=_headers(key_b)
    ).status_code == 404


def test_shortcode_verification_requires_approved_kyc_tenant(client, admin_token):
    tenant_id, tenant_key = _auth_for_tenant("tenant-approval")
    request = client.post(
        "/api/v1/merchant/tenancy/shortcodes", headers=_headers(tenant_key),
        json={"provider": "mpesa", "shortcode": "876543"},
    )
    assert request.status_code == 201
    shortcode_id = request.json()["id"]
    url = f"/api/v1/admin/tenancy/shortcodes/{shortcode_id}/verify"
    resp = client.post(
        url, headers={"Authorization": f"Bearer {admin_token}"},
        json={"approve": True, "evidence_reference": "provider-proof-001"},
    )
    assert resp.status_code == 409
    with SessionLocal() as db:
        contract = db.query(TenantMerchantContract).filter(
            TenantMerchantContract.tenant_merchant_id == tenant_id
        ).one()
        contract.status = "approved"
        contract.kyc_status = "verified"
        db.commit()
    accepted = client.post(
        url, headers={"Authorization": f"Bearer {admin_token}"},
        json={"approve": True, "evidence_reference": "provider-proof-001"},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["ownership_status"] == "verified"
    assert accepted.json()["enabled"] is False
    assert client.post(
        url, headers={"Authorization": f"Bearer {admin_token}"},
        json={"approve": True, "evidence_reference": "provider-proof-001"},
    ).status_code == 409


def test_tenant_cannot_access_platform_shortcode_verification(client):
    _, tenant_key = _auth_for_tenant("tenant-not-admin")
    assert client.get(
        "/api/v1/admin/tenancy/shortcode-requests",
        headers=_headers(tenant_key),
    ).status_code == 401
