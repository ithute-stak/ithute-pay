"""Tenant financial report isolation, bounded windows and export tests."""
from datetime import datetime, timezone

from core.security import hash_password
from database.models import (
    Application, Merchant, PaymentIntent, Payout, ReconciliationItem,
    Settlement, TenantMerchantContract, TenantUserMembership, User,
)
from database.session import SessionLocal


def seed():
    with SessionLocal() as db:
        master = Merchant(name="Ithute Reporting Master", slug="report-master")
        own = Merchant(name="Merchant A", slug="report-merchant-a")
        other = Merchant(name="Merchant B", slug="report-merchant-b")
        db.add_all([master, own, other])
        db.flush()
        db.add_all([
            TenantMerchantContract(
                master_merchant_id=master.id, tenant_merchant_id=m.id,
                status="approved", kyc_status="verified", custody_mode="own_shortcode",
            ) for m in (own, other)
        ])
        user = User(email="reporting@example.com", full_name="Reports",
                    role="merchant_user", password_hash=hash_password("Password123!"))
        db.add(user)
        db.flush()
        db.add(TenantUserMembership(user_id=user.id, merchant_id=own.id,
                                    role="finance", status="active"))
        apps = [Application(merchant_id=m.id, name="POS", environment="test") for m in (own, other)]
        db.add_all(apps)
        db.flush()
        for m, app, ref, amount in (
            (own, apps[0], "=INJECT()", "12.50"),
            (other, apps[1], "SECRET-OTHER-TENANT", "999.00"),
        ):
            db.add(PaymentIntent(
                merchant_id=m.id, application_id=app.id,
                public_id="pi-" + m.slug, amount=amount, currency="LSL",
                reference=ref, provider="mpesa", status="succeeded",
            ))
            db.add(Payout(
                merchant_id=m.id, application_id=app.id,
                public_id="po-" + m.slug, amount="5.00", currency="LSL",
                reference="po-" + m.slug, destination_phone="26650000000",
                provider="mpesa", status="pending",
            ))
            db.add(ReconciliationItem(
                merchant_id=m.id, provider="mpesa", status="matched",
                reconciliation_date=datetime.now(timezone.utc).date(),
            ))
            db.add(Settlement(
                merchant_id=m.id, public_id="st-" + m.slug,
                amount="5.00", currency="LSL", reference="settle-" + m.slug,
                status="pending",
            ))
        db.commit()
        return own.id, other.id


def login(client):
    response = client.post("/api/v1/auth/login", json={
        "email": "reporting@example.com", "password": "Password123!",
    })
    assert response.status_code == 200, response.text


def route(merchant, suffix):
    return f"/api/v1/tenant-portal/merchants/{merchant}/{suffix}"


def period():
    today = datetime.now(timezone.utc).date().isoformat()
    return {"start": today, "end": today}


def test_finance_user_sees_only_own_transactions(client):
    own, other = seed()
    login(client)
    rows = client.get(route(own, "transactions"), params=period())
    assert rows.status_code == 200, rows.text
    assert len(rows.json()) == 2
    assert all(r["reference"] != "SECRET-OTHER-TENANT" for r in rows.json())
    assert client.get(route(other, "transactions"), params=period()).status_code == 404
    assert client.get(route(own, "transactions"), params={
        **period(), "kind": "collection",
    }).json()[0]["amount"] == "12.50"


def test_summary_is_tenant_scoped_and_is_not_a_balance(client):
    own, other = seed()
    login(client)
    response = client.get(route(own, "reports/summary"), params=period())
    assert response.status_code == 200, response.text
    report = response.json()
    assert sum(r["count"] for r in report["transaction_totals"]) == 2
    assert report["reconciliation_status_counts"] == [{"status": "matched", "count": 1}]
    assert len(report["settlement_totals"]) == 1
    assert report["settlement_totals"][0]["gross_amount"] == "5.00"
    assert "not available balance" in report["disclaimer"]
    assert client.get(route(other, "reports/summary"), params=period()).status_code == 404


def test_csv_is_private_and_formula_safe(client):
    own, other = seed()
    login(client)
    response = client.get(route(own, "reports/transactions.csv"), params=period())
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert "'=INJECT()" in response.text
    assert "SECRET-OTHER-TENANT" not in response.text
    assert client.get(route(other, "reports/transactions.csv"), params=period()).status_code == 404


def test_invalid_date_window_is_rejected(client):
    own, _ = seed()
    login(client)
    response = client.get(route(own, "transactions"), params={
        "start": "2026-01-01", "end": "2026-06-01",
    })
    assert response.status_code == 422
    response = client.get(route(own, "reports/summary"), params={
        "start": "2026-11-03", "end": "2026-11-02",
    })
    assert response.status_code == 422


def test_anonymous_reports_require_login(client):
    own, _ = seed()
    response = client.get(route(own, "reports/summary"), params=period())
    assert response.status_code == 401
