import asyncio
from decimal import Decimal


from integrations.ecocash.client import EcoCashClient, EcoCashRuntimeConfig


def test_ecocash_charge_maps_success(monkeypatch):
    async def fake_request(self, method, path, payload=None):
        assert method == "POST"
        assert path == "/transactions/amount/"
        assert payload["tranType"] == "MER"
        return 200, {
            "transactionId": "MP.TEST.1",
            "clientCorrelator": payload["clientCorrelator"],
            "status": "SUCCESS",
            "statusCode": "200",
            "statusMessage": "Transaction Successful",
        }

    monkeypatch.setattr(EcoCashClient, "_request", fake_request)
    client = EcoCashClient(EcoCashRuntimeConfig(
        username="user",
        password="secret",
        merchant_code="123",
        merchant_pin="1234",
        merchant_number="263700000000",
        terminal_id="TERM001",
        country_code="ZW",
        location="Harare",
        super_merchant_name="EcoCash",
        merchant_name="Ithute Pay Bridge",
        channel="WEB",
        notify_url="https://pay.example.com/api/v1/provider-callbacks/ecocash",
    ))
    result = asyncio.run(client.collect(
        amount=Decimal("5.00"), currency="USD", phone="263700000001",
        transaction_reference="INV-1", third_party_conversation_id="CORR-1", description="Test",
    ))
    assert result.accepted is True
    assert result.status == "succeeded"
    assert result.transaction_id == "MP.TEST.1"


def test_ecocash_rejects_unsupported_currency():
    client = EcoCashClient(EcoCashRuntimeConfig(supported_currencies=["USD", "ZWG"]))
    result = asyncio.run(client.collect(
        amount=Decimal("5.00"), currency="LSL", phone="263700000001",
        transaction_reference="INV-1", third_party_conversation_id="CORR-1", description="Test",
    ))
    assert result.accepted is False
    assert result.response_code == "E003"
