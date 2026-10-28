import asyncio
from decimal import Decimal
import httpx
import pytest

from providers.golink.client import GolinkClient, GolinkConfigurationError, GolinkError, amount_to_minor


def test_amount_conversion():
    assert amount_to_minor(Decimal("10.00")) == 1000
    with pytest.raises(ValueError):
        amount_to_minor(Decimal("1.001"))
    with pytest.raises(ValueError):
        amount_to_minor(Decimal("NaN"))


def test_keys_separated_by_environment():
    with pytest.raises(GolinkConfigurationError):
        GolinkClient("glk_live_example", "sandbox")
    with pytest.raises(GolinkConfigurationError):
        GolinkClient("glk_test_example", "production")


def test_mpesa_collection_contract_and_url():
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"id": "test-payment-id", "status": "PROCESSING"})
    async def run():
        client = GolinkClient("glk_test_example")
        return await client.create_payment(direction="DEBIT", rail="MPESA",
            idempotency_key="attempt-1", amount_minor=1000, currency="LSL",
            payer={"phone": "26650000000"}, payee={"name": "Test Merchant"},
            transport=httpx.MockTransport(handler))
    assert asyncio.run(run())["status"] == "PROCESSING"
    assert str(seen[0].url) == "https://sandbox.transact.golink.co.ls/api/payments"
    assert seen[0].headers["X-Api-Key"] == "glk_test_example"
    assert seen[0].read().find(b'"amountMinor":1000') >= 0


def test_timeout_does_not_retry_or_change_idempotency_key():
    attempts = []
    def handler(request):
        attempts.append(request)
        raise httpx.ConnectError("offline")
    async def run():
        await GolinkClient("glk_test_example").create_payment(
            direction="DEBIT", rail="MPESA", idempotency_key="original-key",
            amount_minor=1000, currency="LSL", payer={}, payee={},
            transport=httpx.MockTransport(handler))
    with pytest.raises(GolinkError, match="outcome unknown"):
        asyncio.run(run())
    assert len(attempts) == 1
