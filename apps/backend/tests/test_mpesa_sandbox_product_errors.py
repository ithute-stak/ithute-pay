import asyncio
from decimal import Decimal
from pathlib import Path

from integrations.mpesa.client import MpesaClient, MpesaRuntimeConfig
from integrations.mpesa.contracts import mpesa_response_guidance
from integrations.mpesa.hardened import HardenedMpesaClient


ROOT = Path(__file__).resolve().parents[3]
PAYMENTS_SERVICE = ROOT / "apps/backend/services/payments.py"


def _sandbox_client() -> MpesaClient:
    return MpesaClient(MpesaRuntimeConfig(
        base_url="https://openapi.m-pesa.com",
        environment="sandbox",
        market="vodacomLES",
        country="LES",
        currency="LSL",
        service_provider_code="000000",
        api_key="unused",
        public_key="unused",
        origin="*",
        session_activation_seconds=0,
        timeout_seconds=60,
    ))


def test_sandbox_single_stage_removes_provider_unsafe_description_punctuation(monkeypatch):
    client = _sandbox_client()
    captured = {}

    async def fake_request(method, suffix, *, params=None, json_body=None):
        captured["method"] = method
        captured["suffix"] = suffix
        captured["body"] = json_body
        return 201, {
            "output_ResponseCode": "INS-0",
            "output_ResponseDesc": "Request processed successfully",
            "output_TransactionID": "tx-1",
        }

    monkeypatch.setattr(client, "_request", fake_request)
    asyncio.run(client.collect(
        amount=Decimal("25.00"),
        currency="LSL",
        phone="000000000001",
        transaction_reference="PAYLINK1",
        third_party_conversation_id="conversation-1",
        description="Sandbox payment-link test",
    ))

    assert captured["suffix"] == "c2bPayment/singleStage/"
    assert captured["body"]["input_PurchasedItemsDesc"] == "Sandbox payment link test"


def test_sandbox_multistage_removes_provider_unsafe_description_punctuation(monkeypatch):
    client = _sandbox_client()
    captured = {}

    async def fake_request(method, suffix, *, params=None, json_body=None):
        captured["method"] = method
        captured["suffix"] = suffix
        captured["body"] = json_body
        return 201, {
            "output_ResponseCode": "INS-0",
            "output_ResponseDesc": "Request processed successfully",
            "output_TransactionID": "tx-2",
            "output_VoucherCode": "voucher-1",
        }

    monkeypatch.setattr(client, "_request", fake_request)
    asyncio.run(client.authorize_collection(
        amount=Decimal("25.00"),
        currency="LSL",
        phone="000000000001",
        transaction_reference="AUTH1",
        third_party_conversation_id="conversation-2",
        description="Sandbox two-stage authorization",
    ))

    assert captured["suffix"] == "c2bPayment/multiStage/"
    assert captured["body"]["input_PurchasedItemsDesc"] == "Sandbox two stage authorization"


def test_production_provider_description_is_safely_normalized():
    client = HardenedMpesaClient(MpesaRuntimeConfig(
        environment="production",
        market="vodacomLES",
        country="LES",
        currency="LSL",
        service_provider_code="000000",
        origin="https://pay.example.com",
    ))
    assert client._item_description("Invoice-2026/08", "Payment") == "Invoice 2026 08"


def test_full_reversal_defaults_to_original_transaction_amount_before_provider_call():
    source = PAYMENTS_SERVICE.read_text(encoding="utf-8")
    compact = "".join(source.split())

    assert "reversal_amount=Decimal(amount)ifamountisnotNoneelseDecimal(transaction.amount)" in compact
    assert "amount=reversal_amount" in compact
    assert "reversal=Reversal(" in compact


def test_mpesa_error_guidance_covers_observed_sandbox_failures():
    description_guidance = mpesa_response_guidance(
        response_code="INS-30",
        response_description="Invalid Purchased Items Description Used",
        environment="sandbox",
        service_provider_code="000000",
    )
    reversal_guidance = mpesa_response_guidance(
        response_code="INS-999",
        response_description="Invalid Use Case",
        environment="sandbox",
        service_provider_code="000000",
    )

    assert description_guidance is not None
    assert "letters/numbers/spaces" in description_guidance
    assert reversal_guidance is not None
    assert "reversal amount" in reversal_guidance
