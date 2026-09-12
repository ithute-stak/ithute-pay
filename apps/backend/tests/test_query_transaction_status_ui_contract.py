from __future__ import annotations

import asyncio
from pathlib import Path

from integrations.base import ProviderResult
from integrations.mpesa.sandbox_matrix import MPESA_OFFICIAL_SANDBOX_MATRIX
from routers.mpesa_certification import MpesaCertificationRunRequest, _execute_case


BACKEND = Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / "frontend"


class _QueryProvider:
    environment = "sandbox"
    base = "https://openapi.m-pesa.com"
    market = "vodacomLES"
    country = "LES"
    shortcode = "000000"

    def __init__(self) -> None:
        self.query_reference: str | None = None
        self.third_party_conversation_id: str | None = None

    async def query(self, *, query_reference: str, third_party_conversation_id: str) -> ProviderResult:
        self.query_reference = query_reference
        self.third_party_conversation_id = third_party_conversation_id
        return ProviderResult(
            accepted=True,
            status="succeeded",
            response_code="INS-0",
            response_description="Request processed successfully",
            conversation_id="query-conversation",
            transaction_id="query-transaction",
            third_party_conversation_id=third_party_conversation_id,
            reversed=False,
            raw={
                "output_ResponseCode": "INS-0",
                "output_ResponseDesc": "Request processed successfully",
                "output_Reversed": False,
                "output_ThirdPartyConversationID": third_party_conversation_id,
            },
        )


def _page() -> str:
    return (FRONTEND / "app/dashboard/testing/page.tsx").read_text(encoding="utf-8")


def _panel() -> str:
    return (FRONTEND / "app/dashboard/testing/official-sandbox-scenarios.tsx").read_text(encoding="utf-8")


def test_query_transaction_status_certification_executes_official_provider_query() -> None:
    provider = _QueryProvider()
    request = MpesaCertificationRunRequest(
        product="query_transaction_status",
        scenario="success_not_reversed",
        amount="25.00",
        currency="LSL",
    )
    result = asyncio.run(_execute_case(provider, request.product, request.scenario, request))
    assert provider.query_reference == "000000000001"
    assert provider.third_party_conversation_id
    assert result["product"] == "query_transaction_status"
    assert result["product_label"] == "Query Transaction Status"
    assert result["trigger_field"] == "QueryReference"
    assert result["trigger_value"] == "000000000001"
    assert result["passed"] is True
    assert result["result"]["reversed"] is False
    assert result["request_evidence"]["input_QueryReference"] == "000000000001"


def test_testing_layout_does_not_duplicate_the_testing_workspace() -> None:
    layout = (FRONTEND / "app/dashboard/testing/layout.tsx").read_text(encoding="utf-8")
    assert "OfficialSandboxScenarios" not in layout
    assert "return children" in layout
    assert "fixed bottom-5 right-5" not in layout


def test_main_mpesa_page_is_one_clean_full_sandbox_and_live_workspace() -> None:
    page = _page()
    workspace = (FRONTEND / "lib/provider-workspaces.ts").read_text(encoding="utf-8")
    assert 'title="M-Pesa testing"' in page
    assert 'Sandbox certification' in page
    assert 'Live production verification' in page
    assert 'Provider certification' in page
    assert 'Gateway smoke tests' in page
    assert 'Download testing DOCX' in page
    assert 'OfficialSandboxScenarios' in page
    assert '/admin/testing/mpesa-live/run' in page
    assert '/admin/testing/mpesa-certification/report.docx' in page
    assert 'href: "/dashboard/testing/query-transaction-status"' not in workspace
    assert not (FRONTEND / "app/dashboard/testing/query-transaction-status/page.tsx").exists()


def test_official_sandbox_panel_is_compact_and_report_ready() -> None:
    panel = _panel()
    assert 'form.executionMode !== "live_sandbox"' in panel
    assert 'MPESA_REPORT_RESULTS_KEY' in panel
    assert 'persistReportResult' in panel
    assert 'request_evidence' in panel
    assert 'Latest provider result' in panel
    assert 'Request evidence' in panel
    assert 'Raw M-Pesa response' in panel
    assert 'provider_outcome_matches' in panel
    assert 'setOpen' not in panel
    assert 'fixed bottom-5 right-5' not in panel


def test_ui_exposes_b2b_and_all_runnable_extended_provider_matrices() -> None:
    panel = _panel()
    page = _page()
    expected = {
        "collection": "c2b",
        "payout": "b2c",
        "transfer": "b2b",
        "query_transaction_status": "query_transaction_status",
        "reversal": "reversal",
        "update_transaction": "update_transaction",
        "direct_debit_create": "direct_debit_create",
        "direct_debit_payment": "direct_debit_payment",
        "query_direct_debit_reference": "query_direct_debit_reference",
        "query_direct_debit_customer": "query_direct_debit_customer",
        "query_direct_debit_mandate": "query_direct_debit_mandate",
        "query_direct_debit_balance": "query_direct_debit_balance",
        "direct_debit_cancel": "direct_debit_cancel",
    }
    for ui_id, product in expected.items():
        assert f'{ui_id}: {{' in panel
        assert f'productKey: "{product}"' in panel
        assert f'id: "{ui_id}"' in page

    assert 'shortLabel: "B2B"' in panel
    assert 'title: "B2B provider scenarios"' in panel
    assert 'VoucherCode from multi-stage C2B' in panel
    assert 'Query Direct Debit - Customer Status scenarios' in panel
    assert 'Query Direct Debit - Mandate Status scenarios' in panel
    assert 'Query Direct Debit - Balance scenarios' in panel


def test_query_status_matrix_still_matches_official_document_values() -> None:
    panel = _panel()
    matrix = MPESA_OFFICIAL_SANDBOX_MATRIX["query_transaction_status"]["cases"]
    expected_values = {
        "success_not_reversed": "000000000001",
        "internal_error": "000000000002",
        "transaction_failed": "000000000003",
        "service_unavailable": "000000000007",
        "success_reversed": "000000000000000000001",
        "missing_reference": "000000000000000000002",
        "internal_error_long": "000000000000000000003",
        "transaction_failed_long": "000000000000000000004",
        "service_unavailable_long": "000000000000000000005",
    }
    assert {key: value["value"] for key, value in matrix.items()} == expected_values
    for label in (
        "Valid Transaction Query",
        "Internal Error",
        "Transaction Failed",
        "Service Not Available",
        "Valid Query (Reversed Transaction)",
        "Missing Reference",
        "Internal Error · long reference",
        "Transaction Failed · long reference",
        "Service Not Available · long reference",
    ):
        assert label in panel
    assert "Long reference ...003 is Internal Error" in panel
    assert "...005 is Service Not Available" in panel
