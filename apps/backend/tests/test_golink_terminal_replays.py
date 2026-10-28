"""Behavioral checks for replay-safe Golink reconciliation using a real SQLite session.

These are sequential tests; PostgreSQL concurrency certification remains separate.
"""
import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from database.models import (
    Application, JournalEntry, Merchant, PaymentIntent, ProviderCallbackLog,
    ProviderTransaction,
)
from database.session import SessionLocal
from providers.golink.inbox_processor import reconcile_golink_inbox_item


class FakeGolink:
    def __init__(self, status):
        self.status = status
        self.calls = 0

    async def get_payment(self, payment_id):
        self.calls += 1
        return {
            "id": payment_id, "status": self.status,
            "idempotencyKey": "fixed-key", "amountMinor": 1000,
            "currency": "LSL", "direction": "DEBIT", "rail": "MPESA",
        }


def seed_payment(db, status="processing"):
    merchant = Merchant(name="Test", slug="golink-replay-test")
    db.add(merchant)
    db.flush()
    app = Application(merchant_id=merchant.id, name="Test")
    db.add(app)
    db.flush()
    payment = PaymentIntent(
        public_id="pi-golink-replay", merchant_id=merchant.id, application_id=app.id,
        amount=Decimal("10.00"), currency="LSL", provider="golink",
        reference="replay-test", customer_phone="26650000000",
        status=status,
    )
    db.add(payment)
    db.flush()
    tx = ProviderTransaction(
        merchant_id=merchant.id, application_id=app.id,
        resource_type="payment_intent", resource_id=payment.id,
        provider="golink", direction="inbound", amount=Decimal("10.00"),
        currency="LSL", status=status, transaction_reference="fixed-key",
        third_party_conversation_id="golink-replay-conversation",
        provider_transaction_id="golink-payment-1",
        raw_request={"rail": "MPESA", "idempotencyKey": "fixed-key"},
    )
    db.add(tx)
    db.flush()
    callbacks = []
    for i in range(2):
        event = ProviderCallbackLog(
            provider="golink", callback_type="outbound_webhook",
            payload_hash=f"{i+1:064x}", processing_status="received",
            raw_payload={"type": "payment.succeeded",
                         "data": {"id": "golink-payment-1"}},
        )
        db.add(event)
        callbacks.append(event)
    db.commit()
    return tx.id, [item.id for item in callbacks]


@pytest.mark.parametrize("status", ["SUCCEEDED", "FAILED"])
def test_two_distinct_webhook_events_only_apply_terminal_once(monkeypatch, status):
    monkeypatch.setenv("GOLINK_RECONCILIATION_ENABLED", "true")
    with SessionLocal() as db:
        txid, callback_ids = seed_payment(db)
    client = FakeGolink(status)
    with SessionLocal() as db:
        first = asyncio.run(reconcile_golink_inbox_item(db, callback_ids[0], client))
        assert first == status.lower()
    with SessionLocal() as db:
        second = asyncio.run(reconcile_golink_inbox_item(db, callback_ids[1], client))
        assert second == "duplicate"
        tx = db.get(ProviderTransaction, txid)
        assert tx.status == status.lower()
        if status == "SUCCEEDED":
            count = db.scalar(select(func.count(JournalEntry.id)).where(
                JournalEntry.source_type == "provider_transaction",
                JournalEntry.source_id == txid,
            ))
            assert count == 1


def test_late_processing_does_not_reverse_success(monkeypatch):
    monkeypatch.setenv("GOLINK_RECONCILIATION_ENABLED", "true")
    with SessionLocal() as db:
        txid, ids = seed_payment(db)
    with SessionLocal() as db:
        assert asyncio.run(reconcile_golink_inbox_item(db, ids[0], FakeGolink("SUCCEEDED"))) == "succeeded"
    with SessionLocal() as db:
        assert asyncio.run(reconcile_golink_inbox_item(db, ids[1], FakeGolink("PROCESSING"))) == "stale"
        assert db.get(ProviderTransaction, txid).status == "succeeded"
