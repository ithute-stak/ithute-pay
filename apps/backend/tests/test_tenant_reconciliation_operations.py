"""Tenant reconciliation operational reporting is scoped and non-financial."""
from datetime import datetime, timedelta, timezone

from core.security import hash_password
from database.models import (
    Merchant, ReconciliationItem, TenantMerchantContract,
    TenantReconciliationException, TenantUserMembership, User,
)
from database.session import SessionLocal


def _seed(role="viewer"):
    with SessionLocal() as db:
        master = Merchant(name="Master Reporting", slug="ops-master")
        own = Merchant(name="Ops Tenant", slug="ops-own")
        foreign = Merchant(name="Foreign Tenant", slug="ops-foreign")
        db.add_all([master, own, foreign])
        db.flush()
        for merchant in (own, foreign):
            db.add(TenantMerchantContract(
                master_merchant_id=master.id, tenant_merchant_id=merchant.id,
                status="approved", kyc_status="verified",
                custody_mode="own_shortcode",
            ))
        viewer = User(email="ops@example.com", full_name="Tenant Viewer",
                      role="merchant_user", password_hash=hash_password("Password123!"))
        investigator = User(email="investigator@example.com", full_name="Investigator",
                            role="merchant_user", password_hash=hash_password("Password123!"))
        db.add_all([viewer, investigator])
        db.flush()
        db.add_all([
            TenantUserMembership(user_id=viewer.id, merchant_id=own.id, status="active", role=role),
            TenantUserMembership(user_id=investigator.id, merchant_id=own.id, status="active", role="finance"),
        ])
        cases = []
        for index, (merchant, status, age, assignee) in enumerate((
            (own, "investigating", 12, investigator.id),
            (own, "escalated", 4, None),
            (own, "open", 1, investigator.id),
            (own, "closed", 90, investigator.id),
            (foreign, "escalated", 60, None),
        )):
            item = ReconciliationItem(
                merchant_id=merchant.id, provider="mpesa",
                status="mismatch", reconciliation_date=datetime.now(timezone.utc).date(),
                expected_amount="20.00", provider_amount="15.00", currency="LSL",
            )
            db.add(item)
            db.flush()
            case = TenantReconciliationException(
                merchant_id=merchant.id, reconciliation_item_id=item.id,
                classification="amount_mismatch", investigation_status=status,
                assigned_user_id=assignee, created_by=viewer.id, updated_by=viewer.id,
            )
            db.add(case)
            db.flush()
            cases.append((case.id, age))
        db.commit()
        # Age cases after flush/commit so ORM insert timestamps cannot override them.
        for case_id, days in cases:
            row = db.get(TenantReconciliationException, case_id)
            row.created_at = datetime.now(timezone.utc) - timedelta(days=days)
        db.commit()
        return own.id, foreign.id, investigator.id


def _login(client):
    response = client.post("/api/v1/auth/login", json={
        "email": "ops@example.com", "password": "Password123!",
    })
    assert response.status_code == 200, response.text


def _url(merchant, export=False):
    base = f"/api/v1/tenant-portal/merchants/{merchant}/reconciliation/operations"
    return base + ("/overdue.csv" if export else "")


def test_operations_counts_ages_and_workloads_only_for_own_tenant(client):
    own, foreign, assigned = _seed()
    _login(client)
    response = client.get(_url(own), params={"overdue_after_days": 7})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total_cases"] == 4
    assert data["open_cases"] == 3
    assert data["closed_cases"] == 1
    assert data["overdue_cases"] == 1
    assert data["escalated_cases"] == 1
    assert data["unassigned_cases"] == 1
    assert data["ageing_buckets"]["8-14"] == 1
    assert data["status_counts"]["closed"] == 1
    assert data["workloads"][0]["assigned_user_id"] == assigned
    assert data["workloads"][0]["overdue"] == 1
    assert len(data["overdue"]) == 1
    assert data["overdue"][0]["age_days"] >= 12
    assert client.get(_url(foreign)).status_code == 404


def test_configurable_threshold_and_private_export(client):
    own, foreign, _ = _seed()
    _login(client)
    response = client.get(_url(own), params={"overdue_after_days": 3})
    assert response.status_code == 200
    assert response.json()["overdue_cases"] == 2
    export = client.get(_url(own, export=True), params={"overdue_after_days": 3})
    assert export.status_code == 200, export.text
    assert export.headers["cache-control"] == "private, no-store"
    assert export.text.count("\n") == 3
    assert client.get(_url(foreign, export=True)).status_code == 404


def test_invalid_threshold_and_anonymous_are_rejected(client):
    own, _, _ = _seed()
    assert client.get(_url(own)).status_code == 401
    _login(client)
    assert client.get(_url(own), params={"overdue_after_days": 0}).status_code == 422
    assert client.get(_url(own), params={"overdue_after_days": 91}).status_code == 422


def test_reporting_does_not_change_financial_or_case_status(client):
    own, _, _ = _seed()
    _login(client)
    client.get(_url(own))
    with SessionLocal() as db:
        assert db.query(ReconciliationItem).filter(ReconciliationItem.merchant_id == own).count() == 4
        assert db.query(ReconciliationItem).filter(
            ReconciliationItem.merchant_id == own,
            ReconciliationItem.status == "mismatch",
        ).count() == 4
        assert db.query(TenantReconciliationException).filter(
            TenantReconciliationException.merchant_id == own,
            TenantReconciliationException.investigation_status == "closed",
        ).count() == 1
