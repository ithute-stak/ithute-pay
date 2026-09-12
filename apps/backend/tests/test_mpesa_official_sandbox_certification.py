from __future__ import annotations

from pathlib import Path

import pytest

from integrations.base import ProviderResult
from integrations.mpesa.client import MpesaError, MpesaRuntimeConfig
from integrations.mpesa.hardened import HardenedMpesaClient
from integrations.mpesa.sandbox_matrix import (
    DIRECT_DEBIT_PAYMENT_SANDBOX_MSISDNS,
    MPESA_DOCUMENTED_NOT_RUNNABLE,
    MPESA_OFFICIAL_SANDBOX_MATRIX,
)
from routers.mpesa_certification import _case_passed


ROOT = Path(__file__).resolve().parents[1]


def client(environment: str = "sandbox") -> HardenedMpesaClient:
    return HardenedMpesaClient(MpesaRuntimeConfig(
        base_url="https://openapi.m-pesa.com",
        environment=environment,
        market="vodacomLES",
        country="LES",
        currency="LSL",
        service_provider_code="000000",
        api_key="test-api-key",
        public_key="test-public-key",
        origin="https://pay.example.test",
        cache_namespace="official-sandbox-matrix",
        session_activation_seconds=0,
        timeout_seconds=2,
    ))


def _dd_payment_body(phone: str) -> dict[str, str]:
    return {
        "input_Country": "LES",
        "input_Currency": "LSL",
        "input_ServiceProviderCode": "000000",
        "input_ThirdPartyConversationID": "CERT1234567890ABCDEF1234567890",
        "input_ThirdPartyReference": "CERTDDPAYMENT1",
        "input_Amount": "25.00",
        "input_CustomerMSISDN": phone,
    }


def test_official_direct_debit_payment_triggers_match_provider_documentation():
    assert DIRECT_DEBIT_PAYMENT_SANDBOX_MSISDNS == {
        "00000000000000000001",
        "00000000000000000002",
        "00000000000000000003",
        "00000000000000000004",
        "00000000000000000005",
    }


def test_official_20_digit_direct_debit_payment_msisdns_are_allowed_only_in_sandbox():
    sandbox = client("sandbox")
    for phone in DIRECT_DEBIT_PAYMENT_SANDBOX_MSISDNS:
        body = _dd_payment_body(phone)
        sandbox._validate_request_contract("directDebitPayment/", params=None, json_body=body)

    production = client("production")
    with pytest.raises(MpesaError, match="Invalid M-Pesa CustomerMSISDN"):
        production._validate_request_contract(
            "directDebitPayment/",
            params=None,
            json_body=_dd_payment_body("00000000000000000001"),
        )


def test_20_digit_direct_debit_trigger_is_not_accepted_by_other_endpoints():
    with pytest.raises(MpesaError, match="Invalid M-Pesa CustomerMSISDN"):
        client()._validate_request_contract(
            "c2bPayment/singleStage/",
            params=None,
            json_body={
                "input_Amount": "25.00",
                "input_CustomerMSISDN": "00000000000000000001",
                "input_Country": "LES",
                "input_Currency": "LSL",
                "input_ServiceProviderCode": "000000",
                "input_TransactionReference": "CERTC2B1",
                "input_ThirdPartyConversationID": "CERT1234567890ABCDEF1234567890",
                "input_PurchasedItemsDesc": "Certification",
            },
        )


def test_provider_matrix_contains_the_exact_core_trigger_sets():
    assert [case["value"] for case in MPESA_OFFICIAL_SANDBOX_MATRIX["c2b"]["cases"].values()] == [
        "000000000001", "000000000002", "000000000003", "000000000004", "000000000005",
        "000000000006", "000000000007", "000000000008", "000000000009",
    ]
    assert [case["value"] for case in MPESA_OFFICIAL_SANDBOX_MATRIX["b2c"]["cases"].values()] == [
        "000000000001", "000000000002", "000000000003", "000000000004",
        "000000000005", "000000000006", "000000000007",
    ]
    assert [case["value"] for case in MPESA_OFFICIAL_SANDBOX_MATRIX["b2b"]["cases"].values()] == [
        "000001", "000002", "000003", "000004", "000005", "000006", "000007",
    ]
    assert MPESA_OFFICIAL_SANDBOX_MATRIX["reversal"]["cases"]["not_owned"]["value"] == "0000000000006"
    assert MPESA_OFFICIAL_SANDBOX_MATRIX["update_transaction"]["cases"]["success"]["value"] == "0000000000001"
    assert MPESA_OFFICIAL_SANDBOX_MATRIX["direct_debit_cancel"]["cases"]["mandate_not_found"]["value"] == "00000000000000000003"


def test_query_direct_debit_state_and_balance_matrix_is_preserved():
    customer = MPESA_OFFICIAL_SANDBOX_MATRIX["query_direct_debit_customer"]["cases"]
    mandate = MPESA_OFFICIAL_SANDBOX_MATRIX["query_direct_debit_mandate"]["cases"]
    balance = MPESA_OFFICIAL_SANDBOX_MATRIX["query_direct_debit_balance"]["cases"]

    assert customer["active"]["value"] == "000000000001"
    assert customer["pending_approval"]["expected_extra"]["account_status"] == "Pending Approval"
    assert customer["locked"]["expected_extra"]["account_status"] == "Locked"
    assert customer["inactive"]["expected_extra"]["account_status"] == "Inactive"
    assert mandate["cancelled"]["expected_extra"]["mandate_status"] == "Cancelled"
    assert mandate["expired"]["expected_extra"]["mandate_status"] == "Expired"
    assert balance["larger_than_500"]["expected_extra"]["sufficient_balance"] is False
    assert balance["smaller_than_500"]["expected_extra"]["sufficient_balance"] is True


def test_success_acceptance_can_be_async_but_state_assertions_still_require_terminal_evidence():
    accepted_async = ProviderResult(
        accepted=True,
        status="processing",
        response_code="INS-0",
        response_description="Request processed successfully",
    )
    passed, _ = _case_passed(accepted_async, {"expected_statuses": ["succeeded"], "expected": "Request processed successfully"})
    assert passed is True

    passed, checks = _case_passed(
        accepted_async,
        {
            "expected_statuses": ["succeeded"],
            "expected": "Active",
            "expected_extra": {"mandate_status": "Active"},
        },
    )
    assert passed is False
    assert checks["extra_matches"]["mandate_status"] is False


def test_v31_query_and_beneficiary_are_not_invented_from_testing_page_alone():
    assert MPESA_DOCUMENTED_NOT_RUNNABLE["query_transaction_status_v31"]["status"] == "documented_not_runnable"
    assert MPESA_DOCUMENTED_NOT_RUNNABLE["query_beneficiary_name"]["status"] == "documented_not_runnable"


def test_test_surface_mounts_certification_and_uses_hardened_gateway_factory():
    routes = (ROOT / "providers/mpesa/routes.py").read_text(encoding="utf-8")
    contract = (ROOT / "routers/testing_contract.py").read_text(encoding="utf-8")
    assert "mpesa_certification" in routes
    assert "build_gateway_provider(config)" in contract
    assert "legacy.live_connection" not in contract
