import asyncio
from decimal import Decimal

from integrations.fnb.client import FnbClient, FnbRuntimeConfig


def test_fnb_live_adapter_never_guesses_missing_operation_path():
    client = FnbClient(FnbRuntimeConfig(
        base_url="https://sandbox.example.invalid",
        client_id="test-client",
        client_secret="test-secret",
        account_id="test-account",
        certificate_reference="secret://fnb/client-certificate",
    ))
    result = asyncio.run(client.collect(
        amount=Decimal("100.00"),
        currency="LSL",
        phone="26650000000",
        transaction_reference="TEST-001",
        third_party_conversation_id="third-001",
        description="FNB adapter safety test",
    ))
    assert result.accepted is False
    assert result.response_code == "FNB_NOT_ONBOARDED"
    assert result.extra["live_request_sent"] is False


def test_fnb_live_payload_remains_locked_even_when_paths_are_configured():
    client = FnbClient(FnbRuntimeConfig(
        base_url="https://sandbox.example.invalid",
        operation_paths={"collect": "/official/path/from-contract"},
    ))
    result = asyncio.run(client.collect(
        amount=Decimal("1.00"),
        currency="LSL",
        phone="26650000000",
        transaction_reference="TEST-002",
        third_party_conversation_id="third-002",
        description="No network request",
    ))
    assert result.response_code == "FNB_ADAPTER_PENDING_SPEC"
    assert result.extra["live_request_sent"] is False
