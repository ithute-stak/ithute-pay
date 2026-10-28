"""Tests of immutable provider-request preparation and disabled execution."""
from decimal import Decimal
from types import SimpleNamespace

import pytest

from providers.golink.attempts import (
    GolinkCollectionAttemptError, prepare_collection_attempt, send_prepared_collection,
)


class FakeSession:
    def __init__(self):
        self.flushed = False
        self.added = []
    def add(self, obj):
        self.added.append(obj)
    def flush(self):
        self.flushed = True


def fixtures():
    payment = SimpleNamespace(
        id="p1", merchant_id="m1", application_id="a1",
        amount=Decimal("10.00"), currency="LSL", customer_phone="26650000000",
    )
    tx = SimpleNamespace(
        provider="golink", resource_type="payment_intent", resource_id="p1",
        merchant_id="m1", application_id="a1", amount=Decimal("10.00"),
        currency="LSL", transaction_reference="stable-1", raw_request={},
        status="created",
    )
    return payment, tx


def test_preparation_persists_stable_minor_unit_request():
    payment, tx = fixtures()
    db = FakeSession()
    payload = prepare_collection_attempt(db, payment=payment, transaction=tx,
                                         rail="MPESA", payee_name="Merchant")
    assert db.flushed and payload["amountMinor"] == 1000
    assert payload["idempotencyKey"] == "stable-1"
    assert tx.raw_request == payload
    assert prepare_collection_attempt(db, payment=payment, transaction=tx,
                                      rail="MPESA", payee_name="Merchant") == payload
    with pytest.raises(GolinkCollectionAttemptError, match="cannot be changed"):
        prepare_collection_attempt(db, payment=payment, transaction=tx,
                                   rail="ECOCASH", payee_name="Merchant")


def test_mismatched_tenant_or_amount_rejected():
    payment, tx = fixtures()
    payment.merchant_id = "m2"
    with pytest.raises(GolinkCollectionAttemptError, match="ownership"):
        prepare_collection_attempt(FakeSession(), payment=payment, transaction=tx,
                                   rail="MPESA", payee_name="Merchant")


def test_collection_execution_disabled_without_network(monkeypatch):
    import asyncio
    monkeypatch.delenv("GOLINK_COLLECTIONS_ENABLED", raising=False)
    _, tx = fixtures()
    with pytest.raises(GolinkCollectionAttemptError, match="disabled"):
        asyncio.run(send_prepared_collection(FakeSession(), transaction=tx, client=None))


def test_unknown_attempt_cannot_be_prepared_again():
    payment, tx = fixtures()
    tx.status = "unknown"
    with pytest.raises(GolinkCollectionAttemptError, match="reconciled"):
        prepare_collection_attempt(FakeSession(), payment=payment, transaction=tx,
                                   rail="MPESA", payee_name="Merchant")


def test_unknown_attempt_cannot_be_sent_again(monkeypatch):
    import asyncio
    monkeypatch.setenv("GOLINK_COLLECTIONS_ENABLED", "true")
    payment, tx = fixtures()
    prepare_collection_attempt(FakeSession(), payment=payment, transaction=tx,
                               rail="MPESA", payee_name="Merchant")
    tx.status = "unknown"
    with pytest.raises(GolinkCollectionAttemptError, match="reconciled"):
        asyncio.run(send_prepared_collection(FakeSession(), transaction=tx, client=None))


def test_changed_persisted_amount_is_rejected_before_network(monkeypatch):
    import asyncio
    monkeypatch.setenv("GOLINK_COLLECTIONS_ENABLED", "true")
    payment, tx = fixtures()
    prepare_collection_attempt(FakeSession(), payment=payment, transaction=tx,
                               rail="MPESA", payee_name="Merchant")
    tx.amount = Decimal("11.00")
    with pytest.raises(GolinkCollectionAttemptError, match="amount differs"):
        asyncio.run(send_prepared_collection(FakeSession(), transaction=tx, client=None))


@pytest.mark.parametrize("corruption,match", [
    ({"idempotencyKey": "bad" + chr(10) + "key"}, "[Ii]dempotency"),
    ({"payer": {}}, "parties"),
    ({"payee": {"name": ""}}, "parties"),
])
def test_corrupted_persisted_collection_never_transitions_or_posts(monkeypatch, corruption, match):
    import asyncio

    monkeypatch.setenv("GOLINK_COLLECTIONS_ENABLED", "true")
    payment, tx = fixtures()
    db = FakeSession()
    prepare_collection_attempt(db, payment=payment, transaction=tx,
                               rail="MPESA", payee_name="Merchant")
    tx.raw_request = {**tx.raw_request, **corruption}

    class NoNetworkClient:
        async def create_payment(self, **kwargs):
            raise AssertionError("Corrupted attempt reached Golink")

    with pytest.raises(GolinkCollectionAttemptError, match=match):
        asyncio.run(send_prepared_collection(db, transaction=tx, client=NoNetworkClient()))
    assert tx.status == "created"


@pytest.mark.parametrize("provider_status", ["SUCCEEDED", "FAILED", "CANCELLED", "PROCESSING"])
def test_synchronous_provider_status_is_not_final_before_reconciliation(monkeypatch, provider_status):
    import asyncio

    monkeypatch.setenv("GOLINK_COLLECTIONS_ENABLED", "true")
    payment, tx = fixtures()
    db = FakeSession()
    db.commit = lambda: None
    prepare_collection_attempt(db, payment=payment, transaction=tx,
                               rail="MPESA", payee_name="Merchant")

    class MockClient:
        async def create_payment(self, **kwargs):
            assert kwargs["idempotency_key"] == "stable-1"
            return {"id": "golink-payment-1", "status": provider_status}

    result = asyncio.run(send_prepared_collection(db, transaction=tx, client=MockClient()))
    assert result == "processing"
    assert tx.status == "processing"
    assert tx.provider_transaction_id == "golink-payment-1"
    assert tx.raw_response["status"] == provider_status
