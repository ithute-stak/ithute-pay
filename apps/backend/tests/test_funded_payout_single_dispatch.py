"""Funded merchant payout dispatch must remain single-shot; no provider network."""
import asyncio
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select, func

from database.models import Application, Merchant, Payout, ProviderTransaction
from database.session import SessionLocal
from services import payments


def seed(suffix: str, *, status: str = "created") -> tuple[str, str]:
    with SessionLocal() as db:
        merchant = Merchant(name="Funded payout guard " + suffix, slug="funded-guard-" + suffix)
        db.add(merchant); db.flush()
        app = Application(merchant_id=merchant.id, name="Funded guard", environment="test")
        db.add(app); db.flush()
        payout = Payout(
            public_id="payout-guard-" + suffix, merchant_id=merchant.id, application_id=app.id,
            amount=Decimal("10.00"), currency="LSL", provider="mpesa",
            destination_phone="26650000000", reference="funded-" + suffix,
            status=status, metadata_json={"funding_account_reference": "funded-test"},
        )
        db.add(payout); db.flush()
        tx = ProviderTransaction(
            merchant_id=merchant.id, application_id=app.id, resource_type="payout",
            resource_id=payout.id, provider="mpesa", direction="outbound",
            amount=Decimal("10.00"), currency="LSL", status="created",
            transaction_reference="FP-" + suffix,
            third_party_conversation_id="FP-CONV-" + suffix,
        )
        db.add(tx); db.commit()
        return payout.id, tx.id


def dependencies(monkeypatch, provider):
    monkeypatch.setattr(payments, "_payout_funding_account",
                        lambda db, payout, for_update=False: SimpleNamespace(id="test-account"))
    monkeypatch.setattr(payments, "calculate_fee_details",
                        lambda *args: SimpleNamespace(amount=Decimal("0.10"), payer="merchant", source="test"))
    monkeypatch.setattr(payments, "reserve_payout", lambda *args, **kwargs: None)
    monkeypatch.setattr(payments, "get_provider", lambda *args, **kwargs: provider)
    monkeypatch.setattr(payments, "require_provider_capability", lambda *args, **kwargs: None)


def test_funded_payout_replay_does_not_send_twice(monkeypatch):
    payout_id, tx_id = seed("repeat")
    calls = []

    class Provider:
        async def payout(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(status="processing")

    dependencies(monkeypatch, Provider())

    def apply(db, transaction, result):
        transaction.status = result.status
        db.add(transaction)

    monkeypatch.setattr(payments, "apply_provider_result", apply)
    for _ in range(2):
        with SessionLocal() as db:
            payout = db.get(Payout, payout_id)
            tx = db.get(ProviderTransaction, tx_id)
            assert asyncio.run(payments._execute_funded_payout(db, payout, tx)).status == "processing"
    assert len(calls) == 1
    with SessionLocal() as db:
        payout = db.get(Payout, payout_id)
        assert payout.metadata_json["funding_reservation_transaction_id"] == tx_id


def test_funded_payout_timeout_is_unknown_not_redispatched(monkeypatch):
    payout_id, tx_id = seed("timeout")
    calls = []

    class Provider:
        async def payout(self, **kwargs):
            calls.append(kwargs)
            raise httpx.ReadTimeout("synthetic response loss")

    dependencies(monkeypatch, Provider())
    for _ in range(2):
        with SessionLocal() as db:
            payout = db.get(Payout, payout_id)
            tx = db.get(ProviderTransaction, tx_id)
            assert asyncio.run(payments._execute_funded_payout(db, payout, tx)).status == "unknown"
    assert len(calls) == 1
    with SessionLocal() as db:
        assert db.get(ProviderTransaction, tx_id).status == "unknown"
        assert db.get(Payout, payout_id).metadata_json["funding_reservation_transaction_id"] == tx_id


def test_pending_funding_cannot_dispatch_payout(monkeypatch):
    payout_id, tx_id = seed("not-confirmed", status="funding")
    calls = []

    class Provider:
        async def payout(self, **kwargs):
            calls.append(kwargs)

    dependencies(monkeypatch, Provider())
    with SessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(payments._execute_funded_payout(
                db, db.get(Payout, payout_id), db.get(ProviderTransaction, tx_id)
            ))
        assert exc.value.status_code == 409
        assert db.get(Payout, payout_id).status == "funding"
    assert calls == []
