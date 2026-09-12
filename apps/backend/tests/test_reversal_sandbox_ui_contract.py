from __future__ import annotations

import asyncio
from pathlib import Path

from integrations.base import ProviderResult
from integrations.mpesa.sandbox_matrix import MPESA_OFFICIAL_SANDBOX_MATRIX
from routers.mpesa_certification import MpesaCertificationRunRequest, _execute_case


BACKEND = Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / "frontend"


class _ReversalProvider:
    environment = "sandbox"
    base = "https://openapi.m-pesa.com"
    market = "vodacomLES"
    country = "LES"
    shortcode = "000000"

    def __init__(self) -> None:
        self.transaction_id: str | None = None
        self.third_party_conversation_id: str | None = None
        self.amount = "not-called"

    async def reverse(
        self,
        *,
        transaction_id: str,
        third_party_conversation_id: str,
        amount=None,
    ) -> ProviderResult:
        self.transaction_id = transaction_id
        self.third_party_conversation_id = third_party_conversation_id
        self.amount = amount
        return ProviderResult(
            accepted=True,
            status="succeeded",
            response_code="INS-0",
            response_description="Request processed successfully",
            conversation_id="reversal-conversation",
            transaction_id=transaction_id,
            third_party_conversation_id=third_party_conversation_id,
            raw={
                "output_ResponseCode": "INS-0",
                "output_ResponseDesc": "Request processed successfully",
                "output_TransactionID": transaction_id,
                "output_ThirdPartyConversationID": third_party_conversation_id,
            },
        )


def test_reversal_certification_executes_official_provider_reverse() -> None:
    provider = _ReversalProvider()
    request = MpesaCertificationRunRequest(
        product="reversal",
        scenario="success",
        amount="25.00",
        currency="LSL",
    )
    result = asyncio.run(_execute_case(provider, request.product, request.scenario, request))
    assert provider.transaction_id == "0000000000001"
    assert provider.third_party_conversation_id
    assert provider.amount is None
    assert result["product"] == "reversal"
    assert result["product_label"] == "Reversal"
    assert result["trigger_field"] == "TransactionID"
    assert result["trigger_value"] == "0000000000001"
    assert result["passed"] is True
    assert result["request_evidence"]["input_TransactionID"] == "0000000000001"
    assert result["request_evidence"]["input_ServiceProviderCode"] == "000000"
    assert result["request_evidence"]["provider_endpoint"].endswith("/sandbox/ipg/v2/vodacomLES/reversal/")


def test_reversal_matrix_matches_provider_documentation() -> None:
    cases = MPESA_OFFICIAL_SANDBOX_MATRIX["reversal"]["cases"]
    assert {name: case["value"] for name, case in cases.items()} == {
        "success": "0000000000001",
        "internal_error": "0000000000002",
        "transaction_failed": "0000000000003",
        "invalid_amount": "0000000000004",
        "insufficient_balance": "0000000000005",
        "not_owned": "0000000000006",
        "service_unavailable": "0000000000007",
    }


def test_reversal_ui_exposes_complete_matrix_without_duplicate_layout() -> None:
    panel = (FRONTEND / "app/dashboard/testing/official-sandbox-scenarios.tsx").read_text(encoding="utf-8")
    page = (FRONTEND / "app/dashboard/testing/page.tsx").read_text(encoding="utf-8")
    layout = (FRONTEND / "app/dashboard/testing/layout.tsx").read_text(encoding="utf-8")

    assert "OfficialSandboxScenarios" not in layout
    assert "return children" in layout
    assert 'reversal: {' in panel
    assert 'productKey: "reversal"' in panel
    assert 'capability: "reversal"' in panel
    for label in (
        "Valid Reversal Transaction",
        "Internal Error",
        "Transaction Failed",
        "Invalid Amount Used",
        "Insufficient Balance",
        "This transaction do not belong to you",
        "Service Not Available",
    ):
        assert label in panel
    assert "request_evidence" in panel
    assert "Raw M-Pesa response" in panel
    assert 'id: "reversal"' in page
    assert 'Live production verification' in page
    assert 'Download testing DOCX' in page
