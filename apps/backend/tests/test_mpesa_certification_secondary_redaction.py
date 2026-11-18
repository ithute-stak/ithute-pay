"""No free-form M-PESA provider text or arbitrary metadata in certification exports."""
from integrations.base import ProviderResult
from routers.mpesa_certification import _case_passed, _result_payload
from services.mpesa_certification_evidence import (
    REDACTED,
    safe_mpesa_certification_response,
)


def test_provider_description_under_allowlisted_key_is_still_redacted():
    secret = "apiKey=SECRET_SERVER_CREDENTIAL_123"
    projected = safe_mpesa_certification_response({
        "output_ResponseDesc": secret,
        "output_ResponseCode": "INS-0",
    })
    assert projected["output_ResponseDesc"] == REDACTED
    assert secret not in str(projected)


def test_diagnostic_payload_sanitizes_extra_and_response_description():
    secret = "PRIVATE_CLIENT_TOKEN_DO_NOT_EXPORT"
    result = ProviderResult(
        accepted=False,
        status="failed",
        response_description=secret,
        raw={"output_ResponseDesc": secret},
        extra={
            "account_status": "Active",
            "mandate_status": "Unknown: " + secret,
            "sufficient_balance": True,
            "provider_debug": {"api_key": secret},
            "customer_msisdn": "26650000000",
        },
    )
    public = _result_payload(result)
    assert public["response_description"] == REDACTED
    assert public["provider_response"]["output_ResponseDesc"] == REDACTED
    assert public["extra"] == {"account_status": "Active", "sufficient_balance": True}
    assert secret not in str(public)
    assert "26650000000" not in str(public)


def test_comparison_diagnostics_do_not_echo_unknown_provider_description():
    secret = "session_key=SENSITIVE_SESSION_KEY"
    result = ProviderResult(
        accepted=False, status="failed", response_description=secret,
    )
    passed, checks = _case_passed(
        result,
        {"expected": "Insufficient balance", "expected_statuses": ["failed"]},
    )
    assert passed is False
    assert checks["actual_provider_outcome"] == REDACTED
    assert secret not in str(checks)


def test_documented_provider_business_errors_remain_exportable():
    result = ProviderResult(
        accepted=False, status="failed",
        response_description="Insufficient balance",
        extra={"mandate_status": "Expired"},
    )
    public = _result_payload(result)
    assert public["response_description"] == "Insufficient balance"
    assert public["extra"] == {"mandate_status": "Expired"}
