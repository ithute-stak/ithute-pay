"""Pending provider acknowledgements must not become certified settlements."""
from integrations.base import ProviderResult
from routers.mpesa_certification import _case_passed


def response(status, *, accepted=True, description="Request processed successfully"):
    return ProviderResult(
        accepted=accepted, status=status, response_code="INS-0",
        response_description=description,
    )


def test_pending_accepted_c2b_does_not_pass_terminal_success():
    passed, checks = _case_passed(
        response("processing"),
        {"expected_statuses": ["succeeded"], "expected": "Request processed successfully"},
    )
    assert passed is False
    assert checks["pending_provider_confirmation"] is True
    assert checks["status_matches"] is False
    assert checks["independent_settlement_verified"] is False


def test_unknown_or_failed_with_matching_description_cannot_pass_success():
    for status in ("unknown", "failed"):
        passed, checks = _case_passed(
            response(status),
            {"expected_statuses": ["succeeded"], "expected": "Request processed successfully"},
        )
        assert passed is False
        assert checks["independent_settlement_verified"] is False


def test_terminal_success_matches_scenario_but_is_not_settlement_attestation():
    passed, checks = _case_passed(
        response("succeeded"),
        {"expected_statuses": ["succeeded"], "expected": "Request processed successfully"},
    )
    assert passed is True
    assert checks["pending_provider_confirmation"] is False
    assert checks["independent_settlement_verified"] is False


def test_deterministic_negative_sandbox_fixture_still_works():
    passed, checks = _case_passed(
        response("unknown", accepted=False, description="Missing Reference"),
        {"expected_statuses": ["failed"], "expected": "Missing Reference"},
    )
    assert passed is True
    assert checks["independent_settlement_verified"] is False
