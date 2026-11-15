"""Direct M-PESA funding attempts are single-dispatch and fail closed.

Only fake provider calls, synthetic rows, and disposable test database.
"""
import asyncio
from decimal import Decimal
from types import SimpleNamespace

import httpx
from sqlalchemy import func, select

from database.models import Application, Merchant, Payout, ProviderOperation, ProviderTransaction
from database.session import SessionLocal
from services import payments


def seed(suffix: str, status: str = "created") -> tuple[str, str]:
    with SessionLocal() as db:
        merchant = Merchant(name="Direct funding guard " + suffix, slug="direct-funding-guard-" + suffix)
        db.add(merchant)
        db.flush()
        app = Application(merchant_id=merchant.id, name="Direct funding guard", environment="test")
        db.add(app)
        db.flush()
        payout = Payout(
            public_id="direct-funding-" + suffix, merchant_id=merchant.id,
            application_id=app.id, amount=Decimal("10.00"), currency="LSL",
            provider="mpesa", destination_phone="26650000000",
            reference="FUND-" + suffix, status=status,
            metadata_json={"funding_mode": "direct_mpesa"},
        )
        db.add(payout)
        db.flush()
        tx = ProviderTransaction(
            merchant_id=merchant.id, application_id=app.id,
            resource_type="payout", resource_id=payout.id, provider="mpesa",
            direction="outbound", amount=Decimal("10.00"), currency="LSL",
            status="created", transaction_reference="DF-" + suffix,
            third_party_conversation_id="DF-CONV-" + suffix,
        )
        db.add(tx)
        db.commit()
        return payout.id, tx.id


def fake_preflight(monkeypatch, provider):
    monkeypatch.setattr(payments, "calculate_fee_details",
                        lambda *args: SimpleNamespace(amount=Decimal("0.10"), payer="merchant"))
    monkeypatch.setattr(payments, "direct_funding_configuration", lambda *args: object())
    monkeypatch.setattr(payments, "build_direct_funding_provider", lambda *args: provider)
    monkeypatch.setattr(payments, "platform_funding_receiver", lambda *args: "123456")
    monkeypatch.setattr(payments, "require_provider_capability", lambda *args: None)


def test_response_loss_cannot_trigger_second_funding_transfer(monkeypatch):
    payout_id, tx_id = seed("timeout")
    calls = []

    class FakeProvider:
        async def transfer(self, **kwargs):
            calls.append(kwargs)
            raise httpx.ReadTimeout("simulated lost response")

    fake_preflight(monkeypatch, FakeProvider())
    for _ in range(2):
        with SessionLocal() as db:
            payout = db.get(Payout, payout_id)
            tx = db.get(ProviderTransaction, tx_id)
            result = asyncio.run(payments._start_direct_funding(db, payout, tx))
            assert result.status == "funding_unknown"
    assert len(calls) == 1
    with SessionLocal() as db:
        payout = db.get(Payout, payout_id)
        op = db.get(ProviderOperation, payout.metadata_json["direct_funding_operation_id"])
        assert op.status == "unknown"
        assert op.third_party_conversation_id == calls[0]["third_party_conversation_id"]
        assert db.scalar(select(func.count()).select_from(ProviderOperation).where(
            ProviderOperation.resource_type == "payout",
            ProviderOperation.resource_id == payout_id,
            ProviderOperation.operation_type == "payout.direct_funding",
        )) == 1


def test_existing_unconfirmed_funding_status_does_not_dispatch(monkeypatch):
    payout_id, tx_id = seed("unconfirmed", status="funding")
    calls = []

    class FakeProvider:
        async def transfer(self, **kwargs):
            calls.append(kwargs)

    fake_preflight(monkeypatch, FakeProvider())
    with SessionLocal() as db:
        payout = db.get(Payout, payout_id)
        tx = db.get(ProviderTransaction, tx_id)
        assert asyncio.run(payments._start_direct_funding(db, payout, tx)).status == "funding"
    assert calls == []


def test_created_claim_is_rejected_after_previous_attempt(monkeypatch):
    payout_id, tx_id = seed("claimed", status="funding_unknown")
    calls = []

    class FakeProvider:
        async def transfer(self, **kwargs):
            calls.append(kwargs)

    fake_preflight(monkeypatch, FakeProvider())
    with SessionLocal() as db:
        payout = db.get(Payout, payout_id)
        tx = db.get(ProviderTransaction, tx_id)
        assert asyncio.run(payments._start_direct_funding(db, payout, tx)).status == "funding_unknown"
    assert not calls
