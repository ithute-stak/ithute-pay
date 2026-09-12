import asyncio
from decimal import Decimal

from integrations.ecocash.client import EcoCashClient, EcoCashRuntimeConfig
from integrations.ecocash.contracts import (
    ECOCASH_SANDBOX_PIN_MATRIX,
    ECOCASH_SANDBOX_REQUEST_DEFAULTS,
    effective_ecocash_notify_url,
    normalize_ecocash_msisdn,
    validate_ecocash_msisdn_for_sandbox,
)
from services.payments import _provider_phone


def _client() -> EcoCashClient:
    defaults = ECOCASH_SANDBOX_REQUEST_DEFAULTS
    return EcoCashClient(EcoCashRuntimeConfig(
        environment="sandbox",
        username="sandbox-user",
        password="sandbox-password",
        merchant_code="ACCOUNT-CODE",
        merchant_pin="1234",
        merchant_number="ACCOUNT-NUMBER",
        terminal_id=defaults["terminal_id"],
        country_code=defaults["country_code"],
        location=defaults["location"],
        super_merchant_name=defaults["super_merchant_name"],
        merchant_name=defaults["merchant_name"],
        channel=defaults["channel"],
        notify_url="https://pay.example.test/api/v1/provider-callbacks/ecocash",
    ))


def test_ecocash_documented_msisdn_formats_are_not_rewritten_as_lesotho_numbers():
    assert normalize_ecocash_msisdn("+263 77 304 7653") == "263773047653"
    assert normalize_ecocash_msisdn("0773047653") == "0773047653"
    assert normalize_ecocash_msisdn("773047653") == "773047653"
    assert _provider_phone("ecocash", "+263 77 304 7653") == "263773047653"
    assert not _provider_phone("ecocash", "0773047653").startswith("266")


def test_ecocash_sandbox_msisdn_validator_accepts_all_portal_documented_shapes():
    assert validate_ecocash_msisdn_for_sandbox("263773047653") is None
    assert validate_ecocash_msisdn_for_sandbox("0773047653") is None
    assert validate_ecocash_msisdn_for_sandbox("773047653") is None
    assert validate_ecocash_msisdn_for_sandbox("58000001") is not None


def test_ecocash_pin_matrix_matches_authenticated_portal():
    assert ECOCASH_SANDBOX_PIN_MATRIX["success"]["pin"] == "0000"
    assert ECOCASH_SANDBOX_PIN_MATRIX["insufficient_funds"]["pin"] == "1111"
    assert ECOCASH_SANDBOX_PIN_MATRIX["invalid_pin"]["pin"] == "2222"
    assert ECOCASH_SANDBOX_PIN_MATRIX["limit_exceeded"]["pin"] == "9999"


def test_ecocash_legacy_mpesa_callback_default_is_repaired():
    url = effective_ecocash_notify_url("http://localhost:8001/api/v1/provider-callbacks/mpesa/callback")
    assert url.endswith("/api/v1/provider-callbacks/ecocash")
    assert "/mpesa" not in url


def test_charge_request_matches_instant_payment_v1_shape(monkeypatch):
    client = _client()
    captured = {}

    async def fake_request(method, path, *, payload=None):
        captured["method"] = method
        captured["path"] = path
        captured["payload"] = payload
        return 200, {
            "transactionId": "ECO-TX-1",
            "clientCorrelator": "CORR-1",
            "status": "PENDING",
            "statusCode": "200",
            "statusMessage": "Transaction Successful",
            "endUserId": "773047653",
        }

    monkeypatch.setattr(client, "_request", fake_request)
    result = asyncio.run(client.collect(
        amount=Decimal("2.00"),
        currency="USD",
        phone="773047653",
        transaction_reference="TEST-001",
        third_party_conversation_id="CORR-1",
        description="EcoCash Sandbox",
    ))

    assert captured["method"] == "POST"
    assert captured["path"] == "/transactions/amount/"
    payload = captured["payload"]
    assert payload["clientCorrelator"] == "CORR-1"
    assert payload["referenceCode"] == "TEST-001"
    assert payload["tranType"] == "MER"
    assert payload["endUserId"] == "773047653"
    assert payload["transactionOperationStatus"] == "Charged"
    assert payload["paymentAmount"]["charginginformation"] == {
        "amount": 2.0,
        "currency": "USD",
        "description": "EcoCash Sandbox",
    }
    assert payload["paymentAmount"]["chargeMetaData"]["channel"] == "POS"
    assert payload["merchantCode"] == "ACCOUNT-CODE"
    assert payload["merchantPin"] == "1234"
    assert payload["merchantNumber"] == "ACCOUNT-NUMBER"
    assert payload["countryCode"] == "ZW"
    assert payload["terminalID"] == "UAT00003"
    assert payload["location"] == "Harare"
    assert payload["superMerchantName"] == "ECOCASH"
    assert payload["merchantName"] == "UAT STORE 3"
    assert result.status == "succeeded"
    assert result.transaction_id == "ECO-TX-1"


def test_http_200_pin_failure_message_overrides_pending_status():
    client = _client()
    result = client._result({
        "clientCorrelator": "CORR-FAIL",
        "status": "PENDING",
        "statusCode": "200",
        "statusMessage": "Insufficient Balance",
    }, correlator="CORR-FAIL", http_status=200)

    assert result.accepted is False
    assert result.status == "failed"
    assert result.response_description == "Insufficient Balance"


def test_transaction_lookup_uses_end_user_and_original_correlator(monkeypatch):
    client = _client()
    captured = {}

    async def fake_request(method, path, *, payload=None):
        captured["method"] = method
        captured["path"] = path
        return 200, {
            "transactionId": "ECO-TX-1",
            "clientCorrelator": "CORR-1",
            "status": "SUCCESS",
            "statusCode": "200",
            "statusMessage": "Transaction Successful",
        }

    monkeypatch.setattr(client, "_request", fake_request)
    result = asyncio.run(client.query(
        query_reference="0773047653|CORR-1",
        third_party_conversation_id="UNUSED",
    ))

    assert captured["method"] == "GET"
    assert captured["path"] == "/0773047653/transactions/amount/CORR-1"
    assert result.accepted is True


def test_refund_request_keeps_original_ecocash_reference(monkeypatch):
    client = _client()
    captured = {}

    async def fake_request(method, path, *, payload=None):
        captured["method"] = method
        captured["path"] = path
        captured["payload"] = payload
        return 200, {
            "transactionId": "ECO-REFUND-1",
            "clientCorrelator": "REF-CORR",
            "status": "REFUNDED",
            "statusCode": "200",
            "statusMessage": "Transaction Successful",
        }

    monkeypatch.setattr(client, "_request", fake_request)
    result = asyncio.run(client.reverse(
        transaction_id="ECO-TX-1|773047653|USD|REF-001",
        third_party_conversation_id="REF-CORR",
        amount=Decimal("2.00"),
    ))

    assert captured["method"] == "POST"
    assert captured["path"] == "/transactions/refund/"
    payload = captured["payload"]
    assert payload["tranType"] == "REF"
    assert payload["originalEcocashReference"] == "ECO-TX-1"
    assert payload["endUserId"] == "773047653"
    assert payload["currencyCode"] == "USD"
    assert payload["paymentAmount"]["charginginformation"]["amount"] == 2.0
    assert result.status == "succeeded"
