"""Merchant B2B single-dispatch regression tests; no external provider calls."""
import asyncio
from decimal import Decimal

import httpx
from sqlalchemy import func, select

from database.models import Application, Merchant, ProviderTransaction, Transfer
from database.session import SessionLocal
from integrations.base import ProviderResult
from services import payments


def _transfer():
    with SessionLocal() as db:
        merchant = Merchant(name="Transfer race test", slug="transfer-race")
        db.add(merchant)
        db.flush()
        application = Application(merchant_id=merchant.id, name="Transfer test", environment="test")
        db.add(application)
        db.flush()
        row = Transfer(
            public_id="tr-single-dispatch", merchant_id=merchant.id,
            application_id=application.id, amount=Decimal("10.00"),
            currency="LSL", provider="mpesa", receiver_party_code="123456",
            reference="TEST-TRANSFER", status="created", metadata_json={},
        )
        db.add(row)
        db.commit()
        return row.id


def test_transfer_dispatches_only_once(monkeypatch):
    transfer_id = _transfer()
    calls = []

    class FakeProvider:
        async def transfer(self, **kwargs):
            calls.append(kwargs)
            return ProviderResult(accepted=True, status="processing", response_code="INS-0")

    monkeypatch.setattr(payments, "get_provider", lambda *args, **kwargs: FakeProvider())
    monkeypatch.setattr(payments, "require_provider_capability", lambda *args, **kwargs: None)

    with SessionLocal() as db:
        assert asyncio.run(payments.execute_transfer(db, db.get(Transfer, transfer_id))).status == "processing"
    with SessionLocal() as db:
        assert asyncio.run(payments.execute_transfer(db, db.get(Transfer, transfer_id))).status == "processing"
        tx = db.scalar(select(ProviderTransaction).where(
            ProviderTransaction.resource_type == "transfer",
            ProviderTransaction.resource_id == transfer_id,
        ))
        assert tx is not None
        assert db.scalar(select(func.count()).select_from(ProviderTransaction)) == 1
    assert len(calls) == 1


def test_transfer_timeout_is_unknown_and_not_redispatched(monkeypatch):
    transfer_id = _transfer()
    calls = []

    class TimedOutProvider:
        async def transfer(self, **kwargs):
            calls.append(kwargs)
            raise httpx.ReadTimeout("simulated provider response loss")

    monkeypatch.setattr(payments, "get_provider", lambda *args, **kwargs: TimedOutProvider())
    monkeypatch.setattr(payments, "require_provider_capability", lambda *args, **kwargs: None)

    with SessionLocal() as db:
        assert asyncio.run(payments.execute_transfer(db, db.get(Transfer, transfer_id))).status == "unknown"
    with SessionLocal() as db:
        assert asyncio.run(payments.execute_transfer(db, db.get(Transfer, transfer_id))).status == "unknown"
        tx = db.scalar(select(ProviderTransaction).where(
            ProviderTransaction.resource_type == "transfer",
            ProviderTransaction.resource_id == transfer_id,
        ))
        assert tx is not None
        assert tx.status == "unknown"
        assert tx.transaction_reference == calls[0]["transaction_reference"]
        assert tx.third_party_conversation_id == calls[0]["third_party_conversation_id"]
        assert db.scalar(select(func.count()).select_from(ProviderTransaction)) == 1
    assert len(calls) == 1
