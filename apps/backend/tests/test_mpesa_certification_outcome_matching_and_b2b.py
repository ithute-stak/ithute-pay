from __future__ import annotations

import asyncio
from decimal import Decimal

from integrations.base import ProviderResult
from integrations.mpesa.sandbox_matrix import MPESA_OFFICIAL_SANDBOX_MATRIX
from routers.mpesa_certification import MpesaCertificationRunRequest, _case_passed, _execute_case


def _result(*, status: str, description: str, code: str = "INS-1") -> ProviderResult:
    return ProviderResult(
        accepted=False,
        status=status,
        response_code=code,
        response_description=description,
        raw={"output_ResponseCode": code, "output_ResponseDesc": description},
    )


def test_internal_error_fixture_passes_when_provider_outcome_is_exact_even_if_status_normalizer_differs() -> None:
    case = {"expected": "Internal Error", "expected_statuses": ["unknown"]}
    passed, checks = _case_passed(
        _result(status="failed", description="Internal Error"),
        case,
    )
    assert passed is True
    assert checks["status_matches"] is False
    assert checks["provider_outcome_matches"] is True


def test_missing_reference_fixture_passes_on_exact_provider_outcome() -> None:
    case = {"expected": "Missing Reference", "expected_statuses": ["failed"]}
    passed, checks = _case_passed(
        _result(status="unknown", description="Missing Reference", code="INS-45"),
        case,
    )
    assert passed is True
    assert checks["provider_outcome_matches"] is True


def test_incorrect_pin_portal_label_accepts_provider_generic_transaction_failed_description() -> None:
    case = {"expected": "Transaction Failed [Incorrect PIN]", "expected_statuses": ["failed"]}
    passed, checks = _case_passed(
        _result(status="failed", description="Transaction Failed", code="INS-6"),
        case,
    )
    assert passed is True
    assert checks["provider_outcome_matches"] is True


class _B2BProvider:
    environment = "sandbox"
    base = "https://openapi.m-pesa.com"
    market = "vodacomLES"
    country = "LES"
    shortcode = "000000"

    def __init__(self) -> None:
        self.receiver_party_code: str | None = None

    async def transfer(
        self,
        *,
        amount: Decimal,
        currency: str,
        receiver_party_code: str,
        transaction_reference: str,
        third_party_conversation_id: str,
        description: str,
    ) -> ProviderResult:
        self.receiver_party_code = receiver_party_code
        return ProviderResult(
            accepted=True,
            status="succeeded",
            response_code="INS-0",
            response_description="Request processed successfully",
            transaction_id="B2B-TX",
            third_party_conversation_id=third_party_conversation_id,
            raw={
                "output_ResponseCode": "INS-0",
                "output_ResponseDesc": "Request processed successfully",
                "output_TransactionID": "B2B-TX",
                "output_ThirdPartyConversationID": third_party_conversation_id,
            },
        )


def test_b2b_matrix_matches_official_receiver_party_code_triggers() -> None:
    cases = MPESA_OFFICIAL_SANDBOX_MATRIX["b2b"]["cases"]
    assert {name: case["value"] for name, case in cases.items()} == {
        "success": "000001",
        "internal_error": "000002",
        "transaction_failed": "000003",
        "request_timeout": "000004",
        "invalid_amount": "000005",
        "insufficient_balance": "000006",
        "service_unavailable": "000007",
    }


def test_b2b_certification_calls_real_transfer_contract_and_returns_request_evidence() -> None:
    provider = _B2BProvider()
    request = MpesaCertificationRunRequest(product="b2b", scenario="success", amount="25.00", currency="LSL")
    result = asyncio.run(_execute_case(provider, "b2b", "success", request))

    assert provider.receiver_party_code == "000001"
    assert result["passed"] is True
    assert result["trigger_field"] == "ReceiverPartyCode"
    assert result["trigger_value"] == "000001"
    evidence = result["request_evidence"]
    assert evidence["input_ReceiverPartyCode"] == "000001"
    assert evidence["input_PrimaryPartyCode"] == "000000"
    assert evidence["input_Amount"] == "25.00"
    assert evidence["input_Currency"] == "LSL"
    assert evidence["provider_endpoint"].endswith("/sandbox/ipg/v2/vodacomLES/b2bPayment/")
