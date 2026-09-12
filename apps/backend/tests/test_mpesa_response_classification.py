from integrations.mpesa.client import MpesaRuntimeConfig
from integrations.mpesa.hardened import HardenedMpesaClient


def client():
    return HardenedMpesaClient(MpesaRuntimeConfig(
        base_url="https://openapi.m-pesa.com",
        environment="sandbox",
        market="vodacomLES",
        country="LES",
        currency="LSL",
        service_provider_code="000000",
        api_key="test-api-key",
        public_key="test-public-key",
        origin="https://pay.example.test",
        cache_namespace="response-classification",
        session_activation_seconds=0,
        timeout_seconds=2,
    ))


def test_http_500_ins52_is_final_business_failure_not_unknown():
    result = client()._to_result(500, {
        "output_ResponseCode": "INS-52",
        "output_ResponseDesc": "The MandateID used does not correspond to the ThirdPartyReference used.",
    })
    assert result.status == "failed"
    assert result.accepted is False


def test_http_500_ins57_is_final_business_failure_not_unknown():
    result = client()._to_result(500, {
        "output_ResponseCode": "INS-57",
        "output_ResponseDesc": "Either MSISDN or MSISDNToken required",
    })
    assert result.status == "failed"
    assert result.accepted is False


def test_http_500_internal_error_stays_unknown_for_safe_reconciliation():
    result = client()._to_result(500, {
        "output_ResponseCode": "INS-1",
        "output_ResponseDesc": "Internal Error",
    })
    assert result.status == "unknown"
    assert result.accepted is False


def test_http_401_ins6_mandate_business_failure_is_not_session_expiry():
    assert client()._is_explicit_session_auth_failure(401, {
        "output_ResponseCode": "INS-6",
        "output_ResponseDesc": "Mandate does not exist",
    }) is False


def test_other_documented_401_business_validation_is_not_session_expiry():
    assert client()._is_explicit_session_auth_failure(401, {
        "output_ResponseCode": "INS-56",
        "output_ResponseDesc": "Invalid MSISDNToken Used",
    }) is False
