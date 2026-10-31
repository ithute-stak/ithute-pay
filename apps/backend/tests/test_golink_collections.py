"""Contract tests with no network, no payment routing and no real credentials."""
import asyncio
from decimal import Decimal

import pytest

from providers.golink.collections import GolinkCollectionProvider, normalize_payment


class FakeGolink:
    def __init__(self, status="PROCESSING"):
        self.calls = []
        self.status = status

    async def create_payment(self, **kwargs):
        self.calls.append(kwargs)
        return {"id": "golink-test-payment", "status": self.status}

    async def get_payment(self, payment_id):
        return {"id": payment_id, "status": "SUCCEEDED"}


def test_payment_statuses_are_fail_closed():
    for external, internal in [
        ("PENDING", "processing"), ("PROCESSING", "processing"),
        ("SUCCEEDED", "succeeded"), ("FAILED", "failed"),
        ("CANCELLED", "cancelled"), ("SURPRISE", "unknown"),
    ]:
        assert normalize_payment({"status": external}).status == internal
    assert normalize_payment({"status": "SURPRISE"}).accepted is False


@pytest.mark.parametrize("rail", ["MPESA", "ECOCASH"])
def test_collections_reuse_stable_reference_and_minor_units(rail):
    fake = FakeGolink()
    provider = GolinkCollectionProvider(fake, rail=rail, payee_name="Test Merchant")

    async def execute():
        return await provider.collect(
            amount=Decimal("10.00"), currency="LSL", phone="26650000000",
            transaction_reference="fixed-attempt-1",
            third_party_conversation_id="internal", description="test",
        )

    result = asyncio.run(execute())
    assert result.status == "processing"
    assert result.transaction_id == "golink-test-payment"
    assert fake.calls == [{
        "direction": "DEBIT", "rail": rail, "idempotency_key": "fixed-attempt-1",
        "amount_minor": 1000, "currency": "LSL",
        "payer": {"phone": "26650000000"}, "payee": {"name": "Test Merchant"},
    }]


def test_query_maps_verified_provider_result():
    provider = GolinkCollectionProvider(FakeGolink(), rail="MPESA", payee_name="Test")
    result = asyncio.run(provider.query(query_reference="golink-test-payment", third_party_conversation_id="unused"))
    assert result.status == "succeeded"


def test_incorrect_amount_does_not_contact_provider():
    fake = FakeGolink()
    provider = GolinkCollectionProvider(fake, rail="MPESA", payee_name="Test")
    with pytest.raises(ValueError):
        asyncio.run(provider.collect(
            amount=Decimal("1.001"), currency="LSL", phone="26650000000",
            transaction_reference="fixed-attempt-1",
            third_party_conversation_id="internal", description="test",
        ))
    assert not fake.calls
