"""Sandbox certification exports must not include raw tokens or voucher codes."""
import asyncio

from integrations.base import ProviderResult
from routers.mpesa_certification import (
    MpesaCertificationRunRequest,
    _execute_case,
    _result_payload,
)
from services.mpesa_certification_evidence import (
    REDACTED,
    safe_mpesa_certification_request,
    safe_mpesa_certification_response,
)


def test_provider_response_exports_only_approved_scalar_diagnostics():
    token = "SECRET_TOKEN_MUST_NEVER_APPEAR"
    source = {
        "output_ResponseCode": "INS-0",
        "output_ResponseDesc": "Request processed successfully",
        "output_TransactionID": "TX-123",
        "sessionKey": token,
        "apiKey": token,
        "output_CustomerMSISDN": "26650000123",
        "unexpected": {"session": token},
        "output_ConversationID": {"unexpected_secret": token},
        "output_ThirdPartyConversationID": ["nested", token],
    }
    projected = safe_mpesa_certification_response(source)
    assert projected["output_ResponseCode"] == "INS-0"
    assert projected["output_TransactionID"] == "TX-123"
    assert "output_ConversationID" not in projected
    assert "output_ThirdPartyConversationID" not in projected
    assert token not in str(projected)
    assert "26650000123" not in str(projected)
    assert source["sessionKey"] == token  # Non-mutating projection.


def test_unexpected_provider_shapes_fail_closed():
    assert safe_mpesa_certification_response(None) == {}
    assert safe_mpesa_certification_response(["secret"]) == {}
    assert safe_mpesa_certification_response({"output_ResponseCode": ["secret"]}) == {}


def test_public_result_payload_has_redaction_marker():
    token = "PRIVATE_API_KEY_XYZ"
    result = ProviderResult(
        accepted=True, status="succeeded", response_code="INS-0",
        raw={"output_ResponseCode": "INS-0", "privateSession": token},
    )
    payload = _result_payload(result)
    assert payload["provider_response"] == {"output_ResponseCode": "INS-0"}
    assert payload["provider_response_redacted"] is True
    assert token not in str(payload)


def test_voucher_is_redacted_without_mutating_request():
    voucher = "SENSITIVE_VOUCHER_SECRET"
    req = {"input_VoucherCode": voucher, "input_Country": "LES"}
    projected = safe_mpesa_certification_request(req)
    assert projected == {"input_VoucherCode": REDACTED, "input_Country": "LES"}
    assert req["input_VoucherCode"] == voucher


def test_update_transaction_sends_voucher_to_provider_but_never_exports_it():
    voucher = "SENSITIVE_VOUCHER_CODE_456"
    class SandboxProvider:
        environment = "sandbox"
        country = "LES"
        shortcode = "000000"
        async def update_authorization(self, **kwargs):
            assert kwargs["voucher_code"] == voucher
            return ProviderResult(
                accepted=True, status="succeeded", response_code="INS-0",
                response_description="Request processed successfully",
                raw={
                    "output_ResponseCode": "INS-0",
                    "privateToken": "SECRET_API_KEY_NEVERSHARE",
                },
            )

    data = asyncio.run(_execute_case(
        SandboxProvider(),
        "update_transaction",
        "success",
        MpesaCertificationRunRequest(
            product="update_transaction",
            scenario="success",
            voucher_code=voucher,
        ),
    ))
    assert data["request_evidence"]["input_VoucherCode"] == REDACTED
    assert data["result"]["provider_response"] == {"output_ResponseCode": "INS-0"}
    assert voucher not in str(data)
    assert "SECRET_API_KEY_NEVERSHARE" not in str(data)
