from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from database.models import Application, Merchant, PaymentIntent, ProviderTransaction
from database.models.operations import RiskDecision
from database.session import SessionLocal


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_compliance_risk_and_connector_governance(client, admin_token):
    with SessionLocal() as db:
        merchant = Merchant(name="Operations lender", slug="operations-lender")
        db.add(merchant); db.commit(); db.refresh(merchant)
        merchant_id = merchant.id

    approved = client.put(f"/api/v1/admin/operations/merchants/{merchant_id}/compliance", headers=headers(admin_token), json={
        "business_registration_number": "REG-2026-1", "tax_number": "TAX-1", "status": "approved",
        "risk_tier": "standard", "transaction_limit": "5000.00", "daily_limit": "10000.00",
    })
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    rule = client.post("/api/v1/admin/operations/risk-rules", headers=headers(admin_token), json={
        "code": "large-payment-review", "name": "Review large payments", "rule_type": "amount",
        "action": "review", "threshold_value": "1000.00", "currency": "LSL",
    })
    assert rule.status_code == 201, rule.text
    decision = client.post("/api/v1/admin/operations/risk-evaluations", headers=headers(admin_token), json={
        "merchant_id": merchant_id, "amount": "1500.00", "currency": "LSL", "provider": "mpesa",
    })
    assert decision.status_code == 201, decision.text
    assert decision.json()["outcome"] == "review"

    connector = client.put("/api/v1/admin/operations/connectors/fnb", headers=headers(admin_token), json={
        "name": "FNB Collections", "category": "bank", "mode": "disabled", "enabled": False,
        "status": "configuration_required", "capabilities": ["collection", "reconciliation"],
    })
    assert connector.status_code == 200, connector.text
    assert connector.json()["enabled"] is False


def test_provider_statement_reconciliation_is_idempotent(client, admin_token):
    with SessionLocal() as db:
        merchant = Merchant(name="Recon lender", slug="recon-lender")
        db.add(merchant); db.flush()
        app = Application(merchant_id=merchant.id, name="Recon", environment="test")
        db.add(app); db.flush()
        payment = PaymentIntent(public_id="pi_recon", application_id=app.id, merchant_id=merchant.id, amount=Decimal("100.00"), currency="LSL", provider="mpesa", payment_method="mobile_money", customer_phone="+26650000000", reference="RECON-1", status="succeeded", metadata_json={})
        db.add(payment); db.flush()
        tx = ProviderTransaction(merchant_id=merchant.id, application_id=app.id, resource_type="payment_intent", resource_id=payment.id, provider="mpesa", direction="inbound", amount=Decimal("100.00"), currency="LSL", status="succeeded", transaction_reference="REF123", third_party_conversation_id="TPC123", provider_transaction_id="MPESA123")
        db.add(tx); db.commit()

    body = {"provider": "mpesa", "currency": "LSL", "statement_date": "2026-08-14", "lines": [{"provider_transaction_id": "MPESA123", "reference": "REF123", "amount": "100.00", "currency": "LSL", "status": "succeeded"}]}
    first = client.post("/api/v1/admin/operations/reconciliation-runs", headers=headers(admin_token), json=body)
    assert first.status_code == 201, first.text
    assert first.json()["matched_count"] == 1
    assert first.json()["exception_count"] == 0
    second = client.post("/api/v1/admin/operations/reconciliation-runs", headers=headers(admin_token), json=body)
    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]


def test_payment_confirmation_applies_blocking_risk_rule(client, merchant_api_key):
    with SessionLocal() as db:
        app = db.scalar(select(Application))
        merchant = db.get(Merchant, app.merchant_id)
        from database.models.operations import RiskRule
        db.add(RiskRule(code="block-very-large", name="Block very large payments", rule_type="amount", action="block", threshold_value=Decimal("2000.00"), currency="LSL", enabled=True))
        db.commit()
    response = client.post("/api/v1/payment-intents", headers={"Authorization": f"Bearer {merchant_api_key}", "Idempotency-Key": "risk-block-1"}, json={
        "amount": "2500.00", "currency": "LSL", "provider": "mpesa", "payment_method": "mobile_money",
        "customer": {"phone": "+26650000000"}, "reference": "RISK-1", "confirm": True,
    })
    assert response.status_code == 403, response.text
    with SessionLocal() as db:
        decision = db.scalar(select(RiskDecision).order_by(RiskDecision.created_at.desc()))
        assert decision is not None
        assert decision.outcome == "block"
