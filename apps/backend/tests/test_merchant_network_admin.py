"""Master merchant administration contracts, with no external financial I/O."""
from database.models import (
    Merchant, MerchantCommercialAgreement, PlatformMerchantSettings,
    TenantMerchantContract, User,
)
from database.session import SessionLocal
from core.security import hash_password


def _merchant(name, slug):
    with SessionLocal() as db:
        merchant = Merchant(name=name, slug=slug)
        db.add(merchant)
        db.commit()
        return merchant.id


def _second_admin(client):
    with SessionLocal() as db:
        user = User(
            email="network-reviewer@example.com", full_name="Network Reviewer",
            role="platform_admin", password_hash=hash_password("Password123!"),
        )
        db.add(user)
        db.commit()
    # Prior admin fixture leaves a browser cookie; clear it before another
    # cookie-authenticated login so CSRF protection is not bypassed.
    client.cookies.clear()
    resp = client.post("/api/v1/auth/login", json={
        "email": "network-reviewer@example.com", "password": "Password123!",
    })
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _auth(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def test_master_and_tenant_enrollment_require_admin_and_safe_defaults(client, admin_token):
    master = _merchant("Ithute Master", "master-admin")
    tenant = _merchant("Example POS", "merchant-example-pos")
    auth = _auth(admin_token)
    master_resp = client.post("/api/v1/admin/merchant-network/master", headers=auth,
                              json={"merchant_id": master})
    assert master_resp.status_code == 201, master_resp.text
    assert master_resp.json()["shared_custody_enabled"] is False
    assert client.post("/api/v1/admin/merchant-network/master", headers=auth,
                       json={"merchant_id": tenant}).status_code == 409
    created = client.post("/api/v1/admin/merchant-network/tenants", headers=auth,
                          json={"merchant_id": tenant, "custody_mode": "own_shortcode"})
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "pending"
    assert created.json()["kyc_status"] == "pending"
    assert client.post("/api/v1/admin/merchant-network/tenants", headers=auth,
                       json={"merchant_id": tenant}).status_code == 409
    assert len(client.get("/api/v1/admin/merchant-network/tenants", headers=auth).json()) == 1
    client.cookies.clear()
    assert client.get("/api/v1/admin/merchant-network/master").status_code == 401
    with SessionLocal() as db:
        assert db.query(PlatformMerchantSettings).one().shared_custody_enabled is False


def test_master_shortcode_cannot_be_approved(client, admin_token):
    master = _merchant("Ithute Master", "master-block")
    tenant = _merchant("No Merchant Shop", "master-block-tenant")
    auth = _auth(admin_token)
    assert client.post("/api/v1/admin/merchant-network/master", headers=auth,
                       json={"merchant_id": master}).status_code == 201
    assert client.post("/api/v1/admin/merchant-network/tenants", headers=auth,
                       json={"merchant_id": tenant, "custody_mode": "master_shortcode"}).status_code == 201
    reviewer = _second_admin(client)
    response = client.post(
        f"/api/v1/admin/merchant-network/tenants/{tenant}/review",
        headers=reviewer, json={"approve": True, "kyc_verified": True,
                                "evidence_reference": "provider-document-1"},
    )
    assert response.status_code == 409
    with SessionLocal() as db:
        assert db.query(TenantMerchantContract).one().status == "pending"


def test_tenant_and_fee_agreement_require_separate_approver(client, admin_token):
    master = _merchant("Ithute Master", "master-agreement")
    tenant = _merchant("POS Merchant", "merchant-agreement")
    creator = _auth(admin_token)
    reviewer = _second_admin(client)
    assert client.post("/api/v1/admin/merchant-network/master", headers=creator,
                       json={"merchant_id": master}).status_code == 201
    assert client.post("/api/v1/admin/merchant-network/tenants", headers=creator,
                       json={"merchant_id": tenant}).status_code == 201
    review_url = f"/api/v1/admin/merchant-network/tenants/{tenant}/review"
    payload = {"approve": True, "kyc_verified": True,
               "evidence_reference": "verified-kyc-proof"}
    assert client.post(review_url, headers=creator, json=payload).status_code == 409
    approved = client.post(review_url, headers=reviewer, json=payload)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    proposal = client.post(
        f"/api/v1/admin/merchant-network/tenants/{tenant}/agreements",
        headers=creator,
        json={"version": 1, "inbound_fixed_fee": "1.50",
              "outbound_fixed_fee": "2.00", "provider_cost_payer": "tenant"},
    )
    assert proposal.status_code == 201, proposal.text
    agreement_id = proposal.json()["id"]
    approval_url = f"/api/v1/admin/merchant-network/agreements/{agreement_id}/approve"
    assert client.post(approval_url, headers=creator).status_code == 409
    accepted = client.post(approval_url, headers=reviewer)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "approved"
    assert client.post(approval_url, headers=reviewer).status_code == 409
    with SessionLocal() as db:
        agreement = db.query(MerchantCommercialAgreement).one()
        assert str(agreement.inbound_fixed_fee) == "1.50"
        assert agreement.approved_by is not None


def test_suspension_blocks_future_shortcode_approval(client, admin_token):
    # No payment adapter changes are implied: this enforces administrative state
    # and verifies new provider accounts remain disabled.
    master = _merchant("Ithute Master", "master-suspension")
    tenant = _merchant("Shop", "merchant-suspension")
    creator, reviewer = _auth(admin_token), _second_admin(client)
    assert client.post("/api/v1/admin/merchant-network/master", headers=creator,
                       json={"merchant_id": master}).status_code == 201
    assert client.post("/api/v1/admin/merchant-network/tenants", headers=creator,
                       json={"merchant_id": tenant}).status_code == 201
    assert client.post(f"/api/v1/admin/merchant-network/tenants/{tenant}/review",
                       headers=reviewer, json={
                           "approve": True, "kyc_verified": True,
                           "evidence_reference": "verified-kyc-proof",
                       }).status_code == 200
    result = client.post(f"/api/v1/admin/merchant-network/tenants/{tenant}/suspend",
                         headers=reviewer)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "suspended"
