"""Sandbox-only provider status query contract regression tests."""
from dataclasses import dataclass
from decimal import Decimal

import pytest

from integrations.base import ProviderResult
from services.mpesa_pass_through_evidence import ExpectedMovement
from services.mpesa_pass_through_lifecycle import TransactionError
from services.mpesa_pass_through_query_probe import (
    assess_query_response, probe_sandbox_query,
)

EXPECTED = ExpectedMovement("PT_001", Decimal("1010.00"), "LSL", "YYYY", "XXXX")


def provider_result(raw=None, *, accepted=True, normalized_id="MPS_123", reversed=False):
    if raw is None:
        raw = {
            "output_TransactionReference": "PT_001",
            "output_Amount": "1010.00",
            "output_Currency": "LSL",
            "output_PrimaryPartyCode": "YYYY",
            "output_ReceiverPartyCode": "XXXX",
            "output_ResponseTransactionStatus": "Completed",
            "output_TransactionID": "MPS_123",
        }
    return ProviderResult(
        accepted=accepted, status="succeeded", raw=raw,
        transaction_id=normalized_id, reversed=reversed,
    )


def test_complete_raw_evidence_can_be_assessed_but_never_posted():
    decision = assess_query_response(EXPECTED, provider_result())
    assert decision.sufficient_evidence
    assert decision.status == "succeeded"
    assert decision.transaction_id == "MPS_123"


def test_actual_generic_normalized_response_is_insufficient():
    result = ProviderResult(accepted=True, status="succeeded", transaction_id="MPS_123",
                            raw={"output_ResponseCode": "INS-0", "output_TransactionID": "MPS_123"})
    decision = assess_query_response(EXPECTED, result)
    assert not decision.sufficient_evidence
    assert decision.status == "unknown"
    assert "output_Amount" in decision.missing_fields
    assert "output_PrimaryPartyCode" in decision.missing_fields


@pytest.mark.parametrize("key,value", [
    ("output_TransactionReference", "WRONG"),
    ("output_Amount", "1011.00"),
    ("output_Currency", "ZAR"),
    ("output_PrimaryPartyCode", "OTHER"),
    ("output_ReceiverPartyCode", "OTHER"),
    ("output_ResponseTransactionStatus", "Unmapped"),
    ("output_TransactionID", "DIFFERENT"),
])
def test_mismatched_raw_data_does_not_clear_reconciliation(key, value):
    raw = dict(provider_result().raw)
    raw[key] = value
    decision = assess_query_response(EXPECTED, provider_result(raw))
    assert not decision.sufficient_evidence
    assert decision.status == "unknown"


def test_reversed_transaction_is_never_positive_evidence():
    decision = assess_query_response(EXPECTED, provider_result(reversed=True))
    assert not decision.sufficient_evidence


def test_unaccepted_complete_query_cannot_confirm_success():
    decision = assess_query_response(EXPECTED, provider_result(accepted=False))
    assert not decision.sufficient_evidence


@pytest.mark.parametrize("status,expected_status", [
    ("Pending", "processing"), ("Failed", "failed"), ("Unknown", "unknown"),
])
def test_non_success_is_not_automatically_upgraded(status, expected_status):
    raw = dict(provider_result().raw)
    raw["output_ResponseTransactionStatus"] = status
    decision = assess_query_response(EXPECTED, provider_result(raw))
    assert decision.status == expected_status


@dataclass
class FakeSandboxClient:
    environment: str = "sandbox"
    country: str = "LES"
    currency: str = "LSL"
    market: str = "vodacomLES"
    shortcode: str = "YYYY"
    called: int = 0

    async def query(self, *, query_reference: str, third_party_conversation_id: str):
        self.called += 1
        assert query_reference == "PT_001"
        assert third_party_conversation_id == "QUERY_001"
        return provider_result()


@pytest.mark.asyncio
async def test_sandbox_probe_queries_once_and_is_read_only():
    client = FakeSandboxClient()
    decision = await probe_sandbox_query(client, expected=EXPECTED,
                                        third_party_conversation_id="QUERY_001")
    assert client.called == 1
    assert decision.sufficient_evidence


@pytest.mark.asyncio
async def test_production_client_is_rejected_without_network_call():
    client = FakeSandboxClient(environment="production")
    with pytest.raises(TransactionError, match="sandbox"):
        await probe_sandbox_query(client, expected=EXPECTED,
                                  third_party_conversation_id="QUERY_001")
    assert client.called == 0


@pytest.mark.asyncio
async def test_wrong_credential_shortcode_is_rejected():
    client = FakeSandboxClient(shortcode="XXXX")
    with pytest.raises(TransactionError):
        await probe_sandbox_query(client, expected=EXPECTED,
                                  third_party_conversation_id="QUERY_001")
    assert client.called == 0


@pytest.mark.asyncio
async def test_oversized_reference_is_rejected_before_network_call():
    client = FakeSandboxClient()
    expected = ExpectedMovement("PT_" + "A" * 35, Decimal("1010"), "LSL", "YYYY", "XXXX")
    with pytest.raises(TransactionError, match="reference"):
        await probe_sandbox_query(client, expected=expected,
                                  third_party_conversation_id="QUERY_001")
    assert client.called == 0
