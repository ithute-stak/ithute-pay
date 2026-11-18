"""Top-level certification evidence must enforce the same provider-field rules as nested evidence."""
from integrations.base import ProviderResult
from routers.mpesa_certification import _result_payload, _case_passed


def test_top_level_provider_fields_reject_secret_bearing_values():
    secret = "api_key=SECRET_123 customer=26650000000"
    result = ProviderResult(
        accepted=False,
        status="failed",
        response_code=secret,
        response_description=secret,
        conversation_id=secret,
        transaction_id=secret,
        third_party_conversation_id=secret,
        reversed=None,
        raw={"output_ResponseCode": secret},
    )
    public = _result_payload(result)
    assert public["status"] == "failed"
    assert public["response_code"] is None
    assert public["conversation_id"] is None
    assert public["transaction_id"] is None
    assert public["third_party_conversation_id"] is None
    assert public["response_description"] == "[REDACTED]"
    assert secret not in str(public)


def test_top_level_provider_fields_preserve_valid_diagnostics():
    result = ProviderResult(
        accepted=True,
        status="processing",
        response_code="INS-0",
        conversation_id="abc-123:xyz",
        transaction_id="TXN.123",
        third_party_conversation_id="C-123",
        reversed=False,
    )
    public = _result_payload(result)
    assert public["accepted"] is True
    assert public["status"] == "processing"
    assert public["response_code"] == "INS-0"
    assert public["conversation_id"] == "abc-123:xyz"
    assert public["transaction_id"] == "TXN.123"
    assert public["third_party_conversation_id"] == "C-123"
    assert public["reversed"] is False


def test_unknown_status_is_not_echoed_or_mistaken_for_success():
    result = ProviderResult(accepted=True, status="failed: Authorization Bearer SECRET_123")
    public = _result_payload(result)
    assert public["status"] == "unknown"
    passed, _ = _case_passed(result, {"expected_statuses": ["succeeded"], "expected": "Success"})
    assert passed is False
    assert "SECRET_123" not in str(public)
