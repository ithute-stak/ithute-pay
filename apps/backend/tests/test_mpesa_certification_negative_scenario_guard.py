"""Wrong provider business failures must never pass a sandbox fixture."""
import pytest

from integrations.base import ProviderResult
from integrations.mpesa.sandbox_matrix import MPESA_OFFICIAL_SANDBOX_MATRIX
from routers.mpesa_certification import _case_passed


def result(status, description, *, accepted=False):
    return ProviderResult(
        accepted=accepted,
        status=status,
        response_code="INS-1",
        response_description=description,
    )


@pytest.mark.parametrize("product,scenario", [
    ("c2b", "incorrect_pin"),
    ("c2b", "request_timeout"),
    ("b2c", "insufficient_balance"),
    ("b2b", "internal_error"),
    ("query_transaction_status", "missing_reference"),
    ("reversal", "not_owned"),
])
def test_wrong_business_failure_does_not_satisfy_expected_negative_fixture(product, scenario):
    case = MPESA_OFFICIAL_SANDBOX_MATRIX[product]["cases"][scenario]
    passed, checks = _case_passed(result("failed", "Unrelated authentication failure"), case)
    assert passed is False
    assert checks["provider_outcome_matches"] is False
    assert checks["negative_fixture_specific_outcome_required"] is True
    assert checks["independent_settlement_verified"] is False


@pytest.mark.parametrize("status", ["unknown", "failed"])
def test_exact_negative_response_remains_accepted_even_with_status_normalization(status):
    case = MPESA_OFFICIAL_SANDBOX_MATRIX["b2c"]["cases"]["request_timeout"]
    passed, checks = _case_passed(result(status, "Request timeout"), case)
    assert passed is True
    assert checks["provider_outcome_matches"] is True


def test_failed_status_cannot_pass_when_expected_error_is_missing():
    passed, _ = _case_passed(result("failed", "Any error"), {"expected_statuses": ["failed"]})
    assert passed is False


@pytest.mark.parametrize("status", ["processing", "succeeded"])
def test_successful_or_pending_status_cannot_pass_negative_fixture(status):
    case = MPESA_OFFICIAL_SANDBOX_MATRIX["c2b"]["cases"]["invalid_amount"]
    passed, checks = _case_passed(result(status, "Invalid Amount Used"), case)
    assert passed is False
    assert checks["provider_outcome_matches"] is True


def test_successful_payment_fixture_remains_unchanged():
    case = MPESA_OFFICIAL_SANDBOX_MATRIX["c2b"]["cases"]["success"]
    passed, checks = _case_passed(result("succeeded", "Request processed successfully", accepted=True), case)
    assert passed is True
    assert checks["negative_fixture_specific_outcome_required"] is False
    assert checks["independent_settlement_verified"] is False
