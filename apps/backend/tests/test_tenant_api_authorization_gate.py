"""Tenant API key authorization is fail-closed at the shared auth boundary.

Tests intentionally model an active application (as could be set by an admin)
to prove activation alone cannot turn tenant credentials into payment access.
"""
from database.models import ApiKey, Application, Merchant, TenantMerchantContract
from database.session import SessionLocal
from core.security import generate_secret, sha256_text


def _seed(*, tenant=True, environment="test", scopes=None, contract_status="approved"):
    scopes = ["events:read"] if scopes is None else scopes
    with SessionLocal() as db:
        merchant = Merchant(name="Tenant Gate Shop", slug="tenant-gate-shop")
        db.add(merchant)
        db.flush()
        if tenant:
            master = Merchant(name="Master Gate", slug="tenant-gate-master")
            db.add(master)
            db.flush()
            db.add(TenantMerchantContract(
                master_merchant_id=master.id, tenant_merchant_id=merchant.id,
                status=contract_status, kyc_status="verified",
                custody_mode="own_shortcode",
            ))
        app = Application(merchant_id=merchant.id, name="POS", environment=environment, status="active")
        db.add(app)
        db.flush()
        prefix = "ipb_test_" if environment == "test" else "ipb_live_"
        secret = generate_secret(prefix, 32)
        db.add(ApiKey(application_id=app.id, name="Scoped Test",
                      prefix=secret[:16], last4=secret[-4:],
                      secret_hash=sha256_text(secret), scopes=scopes))
        db.commit()
        return secret


def _auth(secret):
    return {"Authorization": f"Bearer {secret}"}


def test_active_tenant_key_may_only_read_allowed_scoped_events(client):
    secret = _seed()
    response = client.get("/api/v1/developer/events", headers=_auth(secret))
    assert response.status_code == 200, response.text
    assert response.json() == []
    assert client.get("/api/v1/developer/webhook-endpoints",
                      headers=_auth(secret)).status_code == 403


def test_active_tenant_key_cannot_create_payment_or_webhook(client):
    secret = _seed(scopes=["events:read", "webhooks:read"])
    # Authorization must reject before payload processing, idempotency,
    # callbacks, provider dispatch or any money-moving side effects.
    for path in ("/api/v1/payment-intents", "/api/v1/payouts",
                 "/api/v1/transfers", "/api/v1/developer/webhook-endpoints"):
        result = client.post(path, json={}, headers=_auth(secret))
        assert result.status_code == 403, (path, result.text)


def test_tenant_wildcard_and_empty_scopes_do_not_grant_access(client):
    for scopes in ([], ["*"]):
        secret = _seed(scopes=scopes)
        response = client.get("/api/v1/developer/events", headers=_auth(secret))
        assert response.status_code == 403


def test_suspended_tenant_is_denied_even_when_app_and_key_active(client):
    secret = _seed(contract_status="suspended")
    response = client.get("/api/v1/developer/events", headers=_auth(secret))
    assert response.status_code == 403


def test_live_tenant_key_is_denied_even_on_read_only_endpoint(client):
    secret = _seed(environment="live")
    response = client.get("/api/v1/developer/events", headers=_auth(secret))
    assert response.status_code == 403


def test_legacy_non_tenant_merchant_read_still_works(client):
    secret = _seed(tenant=False)
    response = client.get("/api/v1/developer/events", headers=_auth(secret))
    assert response.status_code == 200, response.text
