from sqlalchemy import select

from database.models import GatewayProviderConfiguration
from database.session import SessionLocal


def auth(token: str):
    return {"Authorization": f"Bearer {token}"}


def _configure_live_b2c_gateway() -> None:
    from services.crypto_service import encrypt_local_secret

    with SessionLocal() as db:
        gateway = db.scalar(
            select(GatewayProviderConfiguration).where(
                GatewayProviderConfiguration.provider == "mpesa",
                GatewayProviderConfiguration.environment == "sandbox",
            )
        )
        if gateway is None:
            gateway = GatewayProviderConfiguration(provider="mpesa", environment="sandbox")
        gateway.mode = "live"
        gateway.enabled = True
        gateway.active = True
        gateway.base_url = "https://openapi.m-pesa.com"
        gateway.market = "vodacomLES"
        gateway.country = "LES"
        gateway.currency = "LSL"
        gateway.service_provider_code = "000000"
        gateway.origin = "pay.example.test"
        gateway.api_key_ciphertext = encrypt_local_secret("test-api-key")
        gateway.public_key = "test-public-key"
        gateway.session_activation_seconds = 0
        gateway.request_timeout_seconds = 2
        gateway.metadata_json = {
            "capabilities": {
                "collection": True,
                "reversal": True,
                "query": True,
                "payout": True,
                "transfer": False,
                "authorization": False,
                "direct_debit": False,
            }
        }
        db.add(gateway)
        db.commit()


def test_bulk_b2c_simulator_creates_individual_payouts(client, admin_token):
    response = client.post(
        "/api/v1/admin/testing/bulk-payout",
        headers=auth(admin_token),
        json={
            "execution_mode": "simulator",
            "scenario": "success",
            "count": 4,
            "amount": "12.50",
            "currency": "LSL",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["product"] == "bulk_payout"
    assert body["passed"] is True
    assert body["status"] == "completed"
    assert body["resource"]["requested_count"] == 4
    assert body["resource"]["passed_count"] == 4
    assert body["resource"]["failed_count"] == 0
    assert body["resource"]["total_amount"] == "50.00"
    assert body["checks"]["sequential_processing"] is True
    assert body["checks"]["network_request_count"] == 0
    items = body["resource"]["items"]
    assert len(items) == 4
    assert all(item["status"] == "succeeded" for item in items)
    assert len({item["reference"] for item in items}) == 4
    assert len({item["payout_id"] for item in items}) == 4


def test_bulk_b2c_simulator_validates_expected_failure_scenario(client, admin_token):
    response = client.post(
        "/api/v1/admin/testing/bulk-payout",
        headers=auth(admin_token),
        json={
            "execution_mode": "simulator",
            "scenario": "insufficient_funds",
            "count": 3,
            "amount": "5.00",
            "currency": "LSL",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["passed"] is True
    assert body["resource"]["passed_count"] == 3
    assert body["checks"]["status_counts"]["failed"] == 3
    assert all(item["status"] == "failed" for item in body["resource"]["items"])


def test_bulk_b2c_live_sandbox_sends_one_provider_request_per_item(client, admin_token, monkeypatch):
    from integrations.base import ProviderResult
    from integrations.mpesa.client import MpesaClient

    _configure_live_b2c_gateway()
    calls = []

    async def fake_payout(self, **kwargs):
        calls.append(kwargs)
        number = len(calls)
        return ProviderResult(
            accepted=True,
            status="succeeded",
            response_code="INS-0",
            response_description="Request processed successfully",
            conversation_id=f"conv-bulk-{number}",
            transaction_id=f"tx-bulk-{number}",
            third_party_conversation_id=kwargs["third_party_conversation_id"],
            raw={
                "output_ResponseCode": "INS-0",
                "output_ResponseDesc": "Request processed successfully",
                "output_ConversationID": f"conv-bulk-{number}",
                "output_TransactionID": f"tx-bulk-{number}",
            },
        )

    monkeypatch.setattr(MpesaClient, "payout", fake_payout)

    response = client.post(
        "/api/v1/admin/testing/bulk-payout",
        headers=auth(admin_token),
        json={
            "execution_mode": "live_sandbox",
            "scenario": "success",
            "count": 3,
            "amount": "7.00",
            "currency": "LSL",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["passed"] is True, body
    assert len(calls) == 3
    assert all(call["phone"] == "000000000001" for call in calls)
    assert body["checks"]["network_request_sent"] is True
    assert body["checks"]["network_request_count"] == 3
    assert body["checks"]["endpoint"].endswith("/sandbox/ipg/v2/vodacomLES/b2cPayment/")
    assert [item["provider_transaction_id"] for item in body["resource"]["items"]] == [
        "tx-bulk-1",
        "tx-bulk-2",
        "tx-bulk-3",
    ]


def test_bulk_b2c_live_sandbox_caps_one_run_at_ten_payouts(client, admin_token):
    _configure_live_b2c_gateway()
    response = client.post(
        "/api/v1/admin/testing/bulk-payout",
        headers=auth(admin_token),
        json={
            "execution_mode": "live_sandbox",
            "scenario": "success",
            "count": 11,
            "amount": "5.00",
            "currency": "LSL",
        },
    )
    assert response.status_code == 422, response.text
    assert "limited to 10 sequential payouts" in response.json()["detail"]
