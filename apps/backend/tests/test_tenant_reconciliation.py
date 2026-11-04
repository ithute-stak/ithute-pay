"""Read-only tenant reconciliation: no cross-merchant evidence leakage."""
from datetime import datetime, timezone

from core.security import hash_password
from database.models import (
    Application, Merchant, ProviderTransaction, ReconciliationItem,
    TenantMerchantContract, TenantUserMembership, User,
)
from database.session import SessionLocal


def _seed():
    today = datetime.now(timezone.utc).date()
    with SessionLocal() as db:
        master = Merchant(name="Master", slug="recon-master")
        own = Merchant(name="Mine", slug="recon-own")
        other = Merchant(name="Other", slug="recon-other")
        db.add_all([master, own, other])
        db.flush()
        for tenant in (own, other):
            db.add(TenantMerchantContract(
                master_merchant_id=master.id, tenant_merchant_id=tenant.id,
                status="approved", kyc_status="verified",
                custody_mode="own_shortcode",
            ))
        user = User(email="reconciliation@example.com",
                    password_hash=hash_password("Password123!"),
                    full_name="Reconciliation", role="merchant_user")
        db.add(user)
        db.flush()
        db.add(TenantUserMembership(
            merchant_id=own.id, user_id=user.id, status="active", role="finance",
        ))
        app_a = Application(merchant_id=own.id, name="Own POS", environment="test")
        app_b = Application(merchant_id=other.id, name="Other POS", environment="test")
        db.add_all([app_a, app_b])
        db.flush()
        tx = ProviderTransaction(
            merchant_id=other.id, application_id=app_b.id,
            resource_type="payout", resource_id="foreign",
            provider="mpesa", direction="outbound",
            amount="500.00", currency="LSL",
            transaction_reference="foreign",
            third_party_conversation_id="other-conversation",
            status="succeeded",
        )
        db.add(tx)
        db.flush()
        own_row = ReconciliationItem(
            merchant_id=own.id, provider="mpesa",
            reconciliation_date=today, status="mismatch",
            expected_amount="20.00", provider_amount="18.00", currency="LSL",
            provider_transaction_id="=EXCEL()",
            # Intentionally malformed cross-tenant reference; never project
            # the foreign gateway's status, identifiers or raw payload.
            gateway_transaction_id=tx.id,
        )
        foreign_row = ReconciliationItem(
            merchant_id=other.id, provider="mpesa",
            reconciliation_date=today, status="matched",
            expected_amount="500.00", provider_amount="500.00",
            provider_transaction_id="PRIVATE-FOREIGN", currency="LSL",
            gateway_transaction_id=tx.id,
        )
        db.add_all([own_row, foreign_row])
        db.commit()
        return own.id, other.id, own_row.id, foreign_row.id, today.isoformat()


def _login(client):
    response = client.post("/api/v1/auth/login", json={
        "email": "reconciliation@example.com", "password": "Password123!",
    })
    assert response.status_code == 200, response.text


def _path(mid, suffix="items"):
    return f"/api/v1/tenant-portal/merchants/{mid}/reconciliation/{suffix}"


def test_reconciliation_list_is_tenant_scoped_and_computes_difference(client):
    own, other, own_item, foreign_item, today = _seed()
    _login(client)
    response = client.get(_path(own), params={"start": today, "end": today})
    assert response.status_code == 200, response.text
    assert len(response.json()) == 1
    item = response.json()[0]
    assert item["id"] == own_item
    assert item["difference"] == "-2.00"
    assert item["gateway_transaction_id"] is None
    assert item["gateway_status"] is None
    assert "PRIVATE-FOREIGN" not in response.text
    assert client.get(_path(other), params={"start": today, "end": today}).status_code == 404
    assert client.get(_path(own), params={"start": today, "end": today, "status": "matched"}).json() == []


def test_reconciliation_detail_hides_foreign_items(client):
    own, _, own_item, foreign_item, _ = _seed()
    _login(client)
    assert client.get(_path(own, f"items/{own_item}")).status_code == 200
    assert client.get(_path(own, f"items/{foreign_item}")).status_code == 404


def test_reconciliation_csv_is_scoped_and_formula_safe(client):
    own, other, _, _, today = _seed()
    _login(client)
    response = client.get(_path(own, "items.csv"), params={"start": today, "end": today})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert "'=EXCEL()" in response.text
    assert "PRIVATE-FOREIGN" not in response.text
    assert client.get(_path(other, "items.csv"), params={"start": today, "end": today}).status_code == 404


def test_reconciliation_invalid_window_and_anonymous_rejected(client):
    own, _, _, _, today = _seed()
    assert client.get(_path(own), params={"start": today, "end": today}).status_code == 401
    _login(client)
    assert client.get(_path(own), params={
        "start": "2026-01-01", "end": "2026-10-01",
    }).status_code == 422
