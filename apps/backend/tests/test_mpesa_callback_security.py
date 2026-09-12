from decimal import Decimal

from sqlalchemy import select

from database.models import ProviderCallbackLog, ProviderTransaction
from database.session import SessionLocal


def auth(token: str):
    return {"Authorization": f"Bearer {token}"}


def _merchant_and_application(client, admin_token):
    merchant = client.post("/api/v1/admin/merchants", headers=auth(admin_token), json={
        "name": "Callback Security Merchant",
        "slug": "callback-security-merchant",
        "email": "callback-security@example.com",
        "phone": "+26650000000",
    })
    assert merchant.status_code == 201, merchant.text
    merchant_id = merchant.json()["id"]
    application = client.post("/api/v1/admin/applications", headers=auth(admin_token), json={
        "merchant_id": merchant_id,
        "name": "Callback Security App",
        "environment": "test",
    })
    assert application.status_code == 201, application.text
    return merchant_id, application.json()["id"]


def test_mpesa_callback_with_wrong_original_conversation_cannot_mutate_transaction(client, admin_token):
    merchant_id, application_id = _merchant_and_application(client, admin_token)
    third = "1234567890abcdef1234567890abcdef"

    with SessionLocal() as db:
        transaction = ProviderTransaction(
            merchant_id=merchant_id,
            application_id=application_id,
            resource_type="security_test",
            resource_id="00000000-0000-0000-0000-000000000001",
            provider="mpesa",
            direction="inbound",
            amount=Decimal("10.00"),
            currency="LSL",
            status="processing",
            transaction_reference="SECURITY1",
            third_party_conversation_id=third,
            conversation_id="provider-conversation-correct",
        )
        db.add(transaction)
        db.commit()
        transaction_id = transaction.id

    client.cookies.clear()
    response = client.post("/api/v1/provider-callbacks/mpesa/result", json={
        "input_OriginalConversationID": "provider-conversation-attacker",
        "input_TransactionID": "TXSHOULDNOTAPPLY",
        "input_ResultCode": "INS-0",
        "input_ResultDesc": "Request processed successfully",
        "input_ThirdPartyConversationID": third,
    })
    assert response.status_code == 200, response.text
    assert response.json()["output_ResponseCode"] == "0"

    with SessionLocal() as db:
        transaction = db.get(ProviderTransaction, transaction_id)
        assert transaction.status == "processing"
        assert transaction.provider_transaction_id is None
        log = db.scalar(select(ProviderCallbackLog).where(
            ProviderCallbackLog.provider == "mpesa",
            ProviderCallbackLog.third_party_conversation_id == third,
        ))
        assert log is not None
        assert log.processing_status == "correlation_mismatch"
        assert "OriginalConversationID" in (log.error_message or "")
