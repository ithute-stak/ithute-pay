"""Real sandbox session probe must not echo secrets from upstream failures."""
import asyncio
from types import SimpleNamespace

import pytest

from integrations.mpesa.client import MpesaError
from routers import testing_contract


def config():
    return SimpleNamespace(
        base_url="https://openapi.m-pesa.com",
        environment="sandbox", mode="live", market="vodacomLES",
        country="LES", currency="LSL", service_provider_code="000000",
        origin="*", 
    )


def run(monkeypatch, error=None):
    monkeypatch.setattr(testing_contract.legacy, "_require_enabled", lambda: None)
    monkeypatch.setattr(
        testing_contract.legacy, "_require_live_gateway", lambda db: config(),
    )
    class Provider:
        async def get_session_key(self, *, force=False):
            assert force is True
            if error:
                raise error
            return "private-session-key-never-return"
    monkeypatch.setattr(
        testing_contract, "build_gateway_provider", lambda cfg: Provider(),
    )
    return asyncio.run(testing_contract.live_connection(db=object(), _=object()))


def test_valid_sandbox_session_returns_success_without_secret(monkeypatch):
    response = run(monkeypatch)
    assert response["ok"] is True
    assert response["session_obtained"] is True
    assert response["environment"] == "sandbox"
    assert "private-session-key" not in str(response)


def test_provider_error_does_not_echo_sensitive_payload(monkeypatch):
    secret = "SENSITIVE_SANDBOX_SESSION_TOKEN_123"
    response = run(monkeypatch, MpesaError(
        secret, status_code=401,
        payload={"output_ResponseDesc": secret, "input_ResultCode": secret,
                 "session_key": secret, "api_key": secret},
    ))
    assert response["ok"] is False
    assert response["http_status"] == 401
    assert response["failure_stage"] == "provider_session_request"
    assert "provider_response" not in response
    assert "response_code" not in response
    assert secret not in str(response)


def test_unexpected_transport_error_does_not_echo_sensitive_message(monkeypatch):
    secret = "SENSITIVE_PROVIDER_API_KEY_456"
    response = run(monkeypatch, RuntimeError(secret))
    assert response["ok"] is False
    assert response["failure_stage"] == "local_configuration_or_transport"
    assert "error_type" not in response
    assert secret not in str(response)


def test_corrupt_encrypted_key_has_actionable_but_secret_free_message(monkeypatch):
    class InvalidToken(Exception):
        pass
    response = run(monkeypatch, InvalidToken("SECRET_ENCRYPTION_KEY"))
    assert response["ok"] is False
    assert response["failure_stage"] == "credential_decryption"
    assert "Re-enter" in response["response_description"]
    assert "SECRET_ENCRYPTION_KEY" not in str(response)
