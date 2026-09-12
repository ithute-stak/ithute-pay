from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from database.models import Event, ProviderCallbackLog, SettlementInstruction
from database.session import SessionLocal
from services.ledger import merchant_balance


def admin_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_client_merchant(client, token: str):
    headers = admin_headers(token)
    merchant = client.post("/api/v1/admin/merchants", headers=headers, json={
        "name": "Maseru Learning Academy",
        "slug": "maseru-learning-academy",
        "email": "finance@school.example",
        "phone": "+26650000000",
    })
    assert merchant.status_code == 201, merchant.text
    merchant_id = merchant.json()["id"]
    application = client.post("/api/v1/admin/applications", headers=headers, json={
        "merchant_id": merchant_id,
        "name": "School Billing",
        "environment": "test",
    })
    assert application.status_code == 201, application.text
    app_id = application.json()["id"]
    return merchant_id, app_id


def test_routed_collection_fee_and_net_settlement(client, admin_token):
    headers = admin_headers(admin_token)
    merchant_id, app_id = _create_client_merchant(client, admin_token)

    profile = client.put(f"/api/v1/admin/gateway/merchants/{merchant_id}/profile", headers=headers, json={
        "merchant_number": "SCH-001",
        "sector": "school",
        "default_application_id": app_id,
        "auto_settle": True,
        "settlement_delay_seconds": 0,
        "enabled": True,
    })
    assert profile.status_code == 200, profile.text

    destination = client.post(f"/api/v1/admin/gateway/merchants/{merchant_id}/settlement-accounts", headers=headers, json={
        "provider": "mpesa",
        "account_type": "business_shortcode",
        "account_reference": "SCHOOL01",
        "currency": "LSL",
        "label": "School merchant wallet",
        "is_default": True,
        "enabled": True,
    })
    assert destination.status_code == 201, destination.text

    package = client.post("/api/v1/admin/gateway/fee-packages", headers=headers, json={
        "code": "school-standard",
        "name": "School Standard",
        "currency": "LSL",
        "active": True,
        "is_default": False,
    })
    assert package.status_code == 201, package.text
    package_id = package.json()["id"]
    rule = client.post(f"/api/v1/admin/gateway/fee-packages/{package_id}/rules", headers=headers, json={
        "operation_type": "collection",
        "provider": "mpesa",
        "fixed_fee": "2.00",
        "percentage_fee": "1.0",
        "payer": "merchant",
        "active": True,
    })
    assert rule.status_code == 201, rule.text
    assigned = client.put(f"/api/v1/admin/gateway/merchants/{merchant_id}/fee-package", headers=headers, json={
        "fee_package_id": package_id,
        "active": True,
    })
    assert assigned.status_code == 200, assigned.text

    client.cookies.clear()
    payment = client.post("/api/v1/public/routed-collections", json={
        "merchant_number": "SCH-001",
        "customer_reference": "STU-2026-0007",
        "phone": "+26659001234",
        "amount": "500.00",
        "currency": "LSL",
        "reference": "TERM-3-FEES",
        "reason": "Term 3 tuition",
        "idempotency_key": "school-payment-2026-0007-1",
        "metadata": {"grade": "Form 4"},
    })
    assert payment.status_code == 201, payment.text
    body = payment.json()
    assert body["status"] == "succeeded"
    assert body["customer_reference"] == "STU-2026-0007"
    assert body["settlement"]["gross_amount"] == "500.00"
    assert body["settlement"]["fee_amount"] == "7.00"
    assert body["settlement"]["net_amount"] == "493.00"
    # auto_settle=True and zero delay executes the settlement immediately.
    assert body["settlement"]["status"] == "succeeded"

    replay = client.post("/api/v1/public/routed-collections", json={
        "merchant_number": "SCH-001",
        "customer_reference": "STU-2026-0007",
        "phone": "+26659001234",
        "amount": "500.00",
        "currency": "LSL",
        "reference": "TERM-3-FEES",
        "reason": "Term 3 tuition",
        "idempotency_key": "school-payment-2026-0007-1",
    })
    assert replay.status_code == 201
    assert replay.json()["payment_id"] == body["payment_id"]

    with SessionLocal() as db:
        settlements = db.scalars(select(SettlementInstruction).where(SettlementInstruction.merchant_id == merchant_id)).all()
        assert len(settlements) == 1
        assert merchant_balance(db, merchant_id, "LSL") == Decimal("0.00")
        payment_event = db.scalar(select(Event).where(Event.event_type == "payment.succeeded").order_by(Event.created_at.desc()))
        assert payment_event is not None
        assert payment_event.data_json["customer_reference"] == "STU-2026-0007"
        assert payment_event.data_json["merchant_number"] == "SCH-001"
        settlement_id = settlements[0].public_id

    executed = client.post(f"/api/v1/admin/gateway/settlement-instructions/{settlement_id}/execute", headers=headers)
    assert executed.status_code == 200, executed.text
    assert executed.json()["status"] == "succeeded"
    with SessionLocal() as db:
        assert merchant_balance(db, merchant_id, "LSL") == Decimal("0.00")


def test_provider_environment_configuration_and_callback_audit(client, admin_token):
    headers = admin_headers(admin_token)
    saved = client.post("/api/v1/admin/gateway/provider-configurations", headers=headers, json={
        "provider": "mpesa",
        "environment": "production",
        "mode": "simulator",
        "enabled": True,
        "active": True,
        "market": "vodacomLES",
        "country": "LES",
        "currency": "LSL",
        "service_provider_code": "GATEWAY01",
        "origin": "https://pay.example",
        "callback_url": "https://pay.example/api/v1/provider-callbacks/mpesa/callback",
        "result_url": "https://pay.example/api/v1/provider-callbacks/mpesa/result",
        "timeout_url": "https://pay.example/api/v1/provider-callbacks/mpesa/timeout",
        "redirect_url": "https://pay.example/payment/return",
    })
    assert saved.status_code == 200, saved.text
    assert saved.json()["active"] is True
    assert "api_key" not in saved.json()

    listing = client.get("/api/v1/admin/gateway/provider-configurations", headers=headers)
    assert listing.status_code == 200
    production = next(x for x in listing.json() if x["environment"] == "production")
    assert production["result_url"].endswith("/mpesa/result")
    assert production["timeout_url"].endswith("/mpesa/timeout")

    client.cookies.clear()
    callback_payload = {
        "input_ThirdPartyConversationID": "UNMATCHED-CALLBACK-1",
        "input_ResultCode": "INS-0",
        "input_ResultDesc": "Request processed successfully",
        "input_TransactionID": "TXTEST0001",
    }
    first = client.post("/api/v1/provider-callbacks/mpesa/result", json=callback_payload)
    assert first.status_code == 200, first.text
    second = client.post("/api/v1/provider-callbacks/mpesa/result", json=callback_payload)
    assert second.status_code == 200, second.text
    with SessionLocal() as db:
        rows = db.scalars(select(ProviderCallbackLog).where(
            ProviderCallbackLog.third_party_conversation_id == "UNMATCHED-CALLBACK-1"
        )).all()
        assert len(rows) == 1
        assert rows[0].duplicate is True
