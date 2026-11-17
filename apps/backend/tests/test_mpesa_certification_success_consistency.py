"""Sandbox terminal success needs acceptance and the expected provider outcome."""
import pytest

from integrations.base import ProviderResult
from integrations.mpesa.sandbox_matrix import MPESA_OFFICIAL_SANDBOX_MATRIX
from routers.mpesa_certification import _case_passed


def response(*, accepted: bool, status: str, description: str):
    return ProviderResult(
        accepted=accepted,
        status=status,
        response_code="INS-0",
        response_description=description,
    )


@pytest.mark.parametrize("product", ["c2b", "b2c", "b2b", "reversal", "direct_debit_create"])
def test_success_fixture_rejects_disagreed_provider_acceptance(product):
    case = MPESA_OFFICIAL_SANDBOX_MATRIX[product]["cases"]["success"]
    passed, checks = _case_passed(response(
        accepted=False, status="succeeded",
        description="Request processed successfully",
    ), case)
    assert passed is False
    assert checks["accepted_matches_terminal_success"] is False
    assert checks["status_matches"] is True
    assert checks["independent_settlement_verified"] is False


@pytest.mark.parametrize("product", ["c2b", "b2c", "b2b", "reversal"])
def test_success_fixture_rejects_wrong_provider_business_outcome(product):
    case = MPESA_OFFICIAL_SANDBOX_MATRIX[product]["cases"]["success"]
    passed, checks = _case_passed(response(
        accepted=True, status="succeeded",
        description="Unrelated provider authentication failure",
    ), case)
    assert passed is False
    assert checks["success_provider_outcome_required"] is True
    assert checks["provider_outcome_matches"] is False


def test_correct_success_fixture_remains_accepted_but_not_settlement_proof():
    case = MPESA_OFFICIAL_SANDBOX_MATRIX["c2b"]["cases"]["success"]
    passed, checks = _case_passed(response(
        accepted=True, status="succeeded",
        description="Request processed successfully",
    ), case)
    assert passed is True
    assert checks["accepted_matches_terminal_success"] is True
    assert checks["provider_outcome_matches"] is True
    assert checks["independent_settlement_verified"] is False


def test_matching_negative_fixture_does_not_require_accepted_true():
    case = MPESA_OFFICIAL_SANDBOX_MATRIX["c2b"]["cases"]["incorrect_pin"]
    passed, checks = _case_passed(response(
        accepted=False, status="failed", description="Transaction Failed",
    ), case)
    assert passed is True
    assert checks["accepted_matches_terminal_success"] is None
    assert checks["independent_settlement_verified"] is False


def test_extra_state_fixture_requires_state_and_acceptance():
    case = {
        "expected_statuses": ["succeeded"],
        "expected": "Active",
        "expected_extra": {"mandate_status": "Active"},
    }
    result = response(
        accepted=True, status="succeeded",
        description="Request processed successfully",
    )
    result.extra["mandate_status"] = "Active"
    passed, checks = _case_passed(result, case)
    assert passed is True
    assert checks["success_provider_outcome_required"] is False
    rejected = response(
        accepted=False, status="succeeded",
        description="Request processed successfully",
    )
    rejected.extra["mandate_status"] = "Active"
    passed, _ = _case_passed(rejected, case)
    assert passed is False
