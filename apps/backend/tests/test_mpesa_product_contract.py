import asyncio

import pytest
from fastapi import HTTPException

from integrations.mpesa.contracts import (
    DEFAULT_MPESA_CAPABILITIES,
    CapabilityGuardedMpesaProvider,
    enabled_mpesa_test_products,
    mpesa_response_guidance,
    normalize_mpesa_capabilities,
)


def test_default_live_mpesa_contract_is_conservative():
    capabilities = normalize_mpesa_capabilities(None)

    assert capabilities == DEFAULT_MPESA_CAPABILITIES
    assert capabilities["collection"] is True
    assert capabilities["reversal"] is True
    assert capabilities["query"] is True
    assert capabilities["payout"] is False
    assert capabilities["transfer"] is False
    assert capabilities["authorization"] is False
    assert capabilities["direct_debit"] is False


def test_test_lab_only_advertises_products_supported_by_capabilities():
    supported = enabled_mpesa_test_products(DEFAULT_MPESA_CAPABILITIES)

    assert "collection" in supported
    assert "checkout" in supported
    assert "payment_link" in supported
    assert "reversal" in supported
    assert "settlement" in supported
    assert "accounting" in supported
    assert "reconciliation" in supported
    assert "webhook_signature" in supported
    assert "payout" not in supported
    assert "transfer" not in supported
    assert "authorization" not in supported
    assert "direct_debit" not in supported


def test_explicitly_enabled_product_becomes_available():
    capabilities = {**DEFAULT_MPESA_CAPABILITIES, "payout": True, "transfer": True}
    supported = enabled_mpesa_test_products(capabilities)

    assert "payout" in supported
    assert "transfer" in supported


def test_invalid_shortcode_response_explains_application_scope_and_known_good_profile():
    guidance = mpesa_response_guidance(
        response_code="INS-13",
        response_description="Invalid Shortcode Used",
        environment="sandbox",
        service_provider_code="0000",
    )

    assert guidance is not None
    assert "0000" in guidance
    assert "000000" in guidance
    assert "Open API portal" in guidance
    assert "previously working Ithute sandbox integration" in guidance


class FakeMpesa:
    def __init__(self):
        self.calls: list[str] = []

    async def collect(self, **_kwargs):
        self.calls.append("collect")
        return "collection-ok"

    async def payout(self, **_kwargs):
        self.calls.append("payout")
        return "payout-ok"


def test_guard_allows_baseline_collection_and_blocks_unapproved_payout():
    fake = FakeMpesa()
    provider = CapabilityGuardedMpesaProvider(fake, DEFAULT_MPESA_CAPABILITIES)

    assert asyncio.run(provider.collect()) == "collection-ok"
    assert fake.calls == ["collect"]

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(provider.payout())

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["capability"] == "payout"
    assert fake.calls == ["collect"]


def test_guard_allows_payout_after_product_is_enabled():
    fake = FakeMpesa()
    provider = CapabilityGuardedMpesaProvider(
        fake,
        {**DEFAULT_MPESA_CAPABILITIES, "payout": True},
    )

    assert asyncio.run(provider.payout()) == "payout-ok"
    assert fake.calls == ["payout"]
