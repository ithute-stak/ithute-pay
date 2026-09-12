import asyncio
from decimal import Decimal

import pytest

from integrations.mpesa.client import MpesaError, MpesaRuntimeConfig
from integrations.mpesa.hardened import HardenedMpesaClient


def mpesa_client(*, environment: str = "sandbox", market: str = "vodacomLES",
                 country: str = "LES", currency: str = "LSL") -> HardenedMpesaClient:
    return HardenedMpesaClient(MpesaRuntimeConfig(
        base_url="https://openapi.m-pesa.com",
        environment=environment,
        market=market,
        country=country,
        currency=currency,
        service_provider_code="000000",
        api_key="test-api-key",
        public_key="test-public-key",
        origin="https://pay.example.test",
        cache_namespace="test-contract",
        session_activation_seconds=0,
        timeout_seconds=2,
    ))


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


class FakeAsyncClient:
    def __init__(self, responses, calls):
        self.responses = responses
        self.calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def test_http_401_ins6_transaction_failed_is_never_replayed(monkeypatch):
    client = mpesa_client()
    session_calls = []
    request_calls = []

    async def fake_session(*, force=False):
        session_calls.append(force)
        return "session-one"

    client.get_session_key = fake_session
    client._auth_header = lambda credential: f"Bearer {credential}"
    responses = [FakeResponse(401, {
        "output_ResponseCode": "INS-6",
        "output_ResponseDesc": "Transaction Failed",
    })]
    monkeypatch.setattr(
        "integrations.mpesa.hardened.httpx.AsyncClient",
        lambda timeout: FakeAsyncClient(responses, request_calls),
    )

    status, payload = asyncio.run(client._request(
        "POST",
        "c2bPayment/singleStage/",
        json_body={
            "input_Amount": "10.00",
            "input_CustomerMSISDN": "000000000001",
            "input_Country": "LES",
            "input_Currency": "LSL",
            "input_ServiceProviderCode": "000000",
            "input_TransactionReference": "T1234C",
            "input_ThirdPartyConversationID": "1234567890abcdef1234567890abcdef",
            "input_PurchasedItemsDesc": "Payment",
        },
    ))

    assert status == 401
    assert payload["output_ResponseCode"] == "INS-6"
    assert len(request_calls) == 1
    assert session_calls == [False]


def test_explicit_session_expiry_refreshes_exactly_once(monkeypatch):
    client = mpesa_client()
    session_calls = []
    request_calls = []

    async def fake_session(*, force=False):
        session_calls.append(force)
        return "session-two" if force else "session-one"

    client.get_session_key = fake_session
    client._auth_header = lambda credential: f"Bearer {credential}"
    responses = [
        FakeResponse(401, {"output_ResponseDesc": "Session key expired"}),
        FakeResponse(201, {
            "output_ResponseCode": "INS-0",
            "output_ResponseDesc": "Request processed successfully",
            "output_TransactionID": "TX123",
        }),
    ]
    monkeypatch.setattr(
        "integrations.mpesa.hardened.httpx.AsyncClient",
        lambda timeout: FakeAsyncClient(responses, request_calls),
    )

    status, payload = asyncio.run(client._request(
        "POST",
        "b2bPayment/",
        json_body={
            "input_Amount": "10.00",
            "input_ReceiverPartyCode": "000001",
            "input_Country": "LES",
            "input_Currency": "LSL",
            "input_PrimaryPartyCode": "000000",
            "input_TransactionReference": "T1234C",
            "input_ThirdPartyConversationID": "1234567890abcdef1234567890abcdef",
            "input_PurchasedItemsDesc": "Stock purchase",
        },
    ))

    assert status == 201
    assert payload["output_ResponseCode"] == "INS-0"
    assert len(request_calls) == 2
    assert session_calls == [False, True]


def test_environment_typo_cannot_silently_become_production():
    client = mpesa_client(environment="prodution")
    with pytest.raises(MpesaError, match="Invalid M-Pesa environment"):
        _ = client.env_segment


def test_vodacom_lesotho_market_identity_and_currency_are_enforced():
    client = mpesa_client(currency="USD")
    with pytest.raises(MpesaError, match="market/country/currency configuration mismatch"):
        client._validate_request_contract("b2cPayment/", params=None, json_body={})

    client = mpesa_client()
    with pytest.raises(MpesaError, match="currency does not match"):
        client._validate_request_contract(
            "b2cPayment/",
            params=None,
            json_body={
                "input_Country": "LES",
                "input_Currency": "USD",
                "input_ServiceProviderCode": "000000",
            },
        )


def test_production_item_description_is_provider_safe_without_mutating_business_record():
    client = mpesa_client(environment="production")
    assert client._item_description("Loan repayment #123 / August", "Payment") == "Loan repayment 123 August"


def test_direct_debit_synchronous_success_without_transaction_id_is_terminal():
    client = mpesa_client()
    result = client._to_result(200, {
        "output_ResponseCode": "INS-0",
        "output_ResponseDesc": "Request processed successfully",
        "output_TransactionReference": "Test123",
        "output_MsisdnToken": "cvgwUBZ3lAO9ivwhWAFeng==",
        "output_ConversationID": "abcdef1234567890abcdef1234567890",
        "output_ThirdPartyConversationID": "1234567890abcdef1234567890abcdef",
    })
    assert result.accepted is True
    assert result.status == "succeeded"


def test_generic_async_acceptance_without_terminal_evidence_remains_processing():
    client = mpesa_client()
    result = client._to_result(201, {
        "output_ResponseCode": "INS-0",
        "output_ResponseDesc": "Request processed successfully",
        "output_ConversationID": "abcdef1234567890abcdef1234567890",
        "output_ThirdPartyConversationID": "1234567890abcdef1234567890abcdef",
    })
    assert result.accepted is True
    assert result.status == "processing"


def test_direct_debit_frequency_contract_is_enforced():
    client = mpesa_client()
    with pytest.raises(MpesaError, match="day range is not allowed"):
        client._validate_request_contract(
            "directDebitCreation/",
            params=None,
            json_body={
                "input_CustomerMSISDN": "000000000001",
                "input_Country": "LES",
                "input_ServiceProviderCode": "000000",
                "input_ThirdPartyReference": "Test123",
                "input_ThirdPartyConversationID": "1234567890abcdef1234567890abcdef",
                "input_AgreedTC": "1",
                "input_FirstPaymentDate": "20260818",
                "input_Frequency": "02",
                "input_StartRangeOfDays": "01",
            },
        )


def test_all_documented_lesotho_provider_methods_keep_the_expected_wire_paths_and_fields():
    client = mpesa_client()
    calls = []

    async def fake_request(method, suffix, *, params=None, json_body=None):
        calls.append((method, suffix, params, json_body))
        payload = {
            "output_ResponseCode": "INS-0",
            "output_ResponseDesc": "Request processed successfully",
            "output_ConversationID": "abcdef1234567890abcdef1234567890",
            "output_ThirdPartyConversationID": "1234567890abcdef1234567890abcdef",
            "output_TransactionID": "TX123456",
        }
        if suffix == "directDebitCreation/":
            payload.pop("output_TransactionID", None)
            payload["output_MandateID"] = "15045"
            payload["output_MsisdnToken"] = "cvgwUBZ3lAO9ivwhWAFeng=="
        if suffix == "queryDirectDebit/":
            payload.pop("output_TransactionID", None)
            payload["output_MandateStatus"] = "Active"
            payload["output_SufficientBalance"] = True
        if suffix == "directDebitCancel/":
            payload.pop("output_TransactionID", None)
            payload["output_TransactionReference"] = "Test123"
        return 201, payload

    client._request = fake_request
    third = "1234567890abcdef1234567890abcdef"

    asyncio.run(client.collect(
        amount=Decimal("10"), currency="LSL", phone="000000000001",
        transaction_reference="C2B123", third_party_conversation_id=third, description="Loan payment",
    ))
    asyncio.run(client.payout(
        amount=Decimal("10"), currency="LSL", phone="000000000001",
        transaction_reference="B2C123", third_party_conversation_id=third, description="Salary payment",
    ))
    asyncio.run(client.transfer(
        amount=Decimal("10"), currency="LSL", receiver_party_code="000001",
        transaction_reference="B2B123", third_party_conversation_id=third, description="Stock purchase",
    ))
    asyncio.run(client.query(query_reference="TX123456", third_party_conversation_id=third))
    asyncio.run(client.reverse(transaction_id="TX123456", third_party_conversation_id=third, amount=Decimal("10")))
    asyncio.run(client.authorize_collection(
        amount=Decimal("10"), currency="LSL", phone="000000000001",
        transaction_reference="AUTH123", third_party_conversation_id=third, description="Reserved payment",
    ))
    asyncio.run(client.update_authorization(
        transaction_id="TX123456", voucher_code="TGS813",
        third_party_conversation_id=third, commit=True,
    ))
    asyncio.run(client.create_mandate(
        phone="000000000001", third_party_reference="Mandate1", third_party_conversation_id=third,
        agreed_terms=True, first_payment_date="2026-08-18", frequency="monthly",
        day_from=1, day_to=25, expiry_date="2027-08-18",
    ))
    asyncio.run(client.charge_mandate(
        amount=Decimal("10"), currency="LSL", third_party_reference="Mandate1",
        third_party_conversation_id=third, phone="000000000001", mandate_id="15045",
    ))
    asyncio.run(client.query_mandate(
        third_party_reference="Mandate1", third_party_conversation_id=third,
        phone="000000000001", mandate_id="15045", balance_amount=Decimal("10"),
    ))
    asyncio.run(client.cancel_mandate(
        third_party_reference="Mandate1", third_party_conversation_id=third,
        phone="000000000001", mandate_id="15045",
    ))

    assert [(method, suffix) for method, suffix, _, _ in calls] == [
        ("POST", "c2bPayment/singleStage/"),
        ("POST", "b2cPayment/"),
        ("POST", "b2bPayment/"),
        ("GET", "queryTransactionStatus/"),
        ("PUT", "reversal/"),
        ("POST", "c2bPayment/multiStage/"),
        ("PUT", "updateTransactionStatus/"),
        ("POST", "directDebitCreation/"),
        ("POST", "directDebitPayment/"),
        ("GET", "queryDirectDebit/"),
        ("PUT", "directDebitCancel/"),
    ]

    c2b_body = calls[0][3]
    assert set(c2b_body) == {
        "input_Amount", "input_CustomerMSISDN", "input_Country", "input_Currency",
        "input_ServiceProviderCode", "input_TransactionReference",
        "input_ThirdPartyConversationID", "input_PurchasedItemsDesc",
    }
    b2c_body = calls[1][3]
    assert "input_PaymentItemsDesc" in b2c_body
    b2b_body = calls[2][3]
    assert b2b_body["input_PrimaryPartyCode"] == "000000"
    assert b2b_body["input_ReceiverPartyCode"] == "000001"
    multi_body = calls[5][3]
    assert multi_body["input_APIVersion"] == "3.1"
    update_body = calls[6][3]
    assert update_body["input_CustomerMSISDN"] == "1"
    assert update_body["input_APIVersion"] == "3.1"
