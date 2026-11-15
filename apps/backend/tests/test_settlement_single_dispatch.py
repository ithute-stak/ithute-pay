"""Settlement dispatch safety: no real network calls or money movement."""
import asyncio
from decimal import Decimal

import httpx
from sqlalchemy import func, select

from database.models import Application, Merchant, ProviderOperation, ProviderTransaction, SettlementInstruction
from database.session import SessionLocal
from integrations.base import ProviderResult
from services import settlements


def _seed(suffix: str) -> str:
    with SessionLocal() as db:
        merchant = Merchant(name="Settlement guard " + suffix, slug="settlement-guard-" + suffix)
        db.add(merchant); db.flush()
        app = Application(merchant_id=merchant.id, name="Settlement guard", environment="test")
        db.add(app); db.flush()
        source = ProviderTransaction(
            merchant_id=merchant.id, application_id=app.id,
            resource_type="payment_intent", resource_id="synthetic-" + suffix,
            provider="mpesa", direction="inbound", amount=Decimal("10.00"),
            currency="LSL", status="succeeded",
            transaction_reference="SG-" + suffix,
            third_party_conversation_id="SG-CONV-" + suffix,
        )
        db.add(source); db.flush()
        row = SettlementInstruction(
            public_id="stl-guard-" + suffix, merchant_id=merchant.id,
            application_id=app.id, source_transaction_id=source.id,
            gross_amount=Decimal("10.00"), fee_amount=Decimal("0.00"),
            net_amount=Decimal("10.00"), currency="LSL", provider="mpesa",
            destination_type="business_shortcode", destination_reference="123456",
            status="pending", attempt_count=0,
        )
        db.add(row); db.commit()
        return row.id


def _stub_prerequisites(monkeypatch, provider):
    monkeypatch.setattr(settlements, "_destination", lambda db, row: ("business_shortcode", "123456"))
    monkeypatch.setattr(settlements, "merchant_balance", lambda *args: Decimal("500.00"))
    monkeypatch.setattr(settlements, "_funding_reference", lambda *args: None)
    monkeypatch.setattr(settlements, "get_provider", lambda *args, **kwargs: provider)
    monkeypatch.setattr(settlements, "require_provider_capability", lambda *args, **kwargs: None)
    # Never post a ledger or emit webhooks in this isolated test.
    def finish(db, *, row, operation, result):
        row.status = result.status
        db.add(row)
        return row
    monkeypatch.setattr(settlements, "finalize_settlement_result", finish)


def test_settlement_replay_does_not_dispatch_twice(monkeypatch):
    sid = _seed("repeat")
    calls = []
    class Provider:
        async def transfer(self, **kwargs):
            calls.append(kwargs)
            return ProviderResult(accepted=True, status="processing", response_code="INS-0")
    _stub_prerequisites(monkeypatch, Provider())
    for _ in range(2):
        with SessionLocal() as db:
            result = asyncio.run(settlements.execute_settlement_instruction(db, db.get(SettlementInstruction, sid)))
            assert result.status == "processing"
    with SessionLocal() as db:
        row = db.get(SettlementInstruction, sid)
        assert row.attempt_count == 1
        assert db.scalar(select(func.count()).select_from(ProviderOperation).where(
            ProviderOperation.resource_type == "settlement_instruction",
            ProviderOperation.resource_id == sid,
        )) == 1
    assert len(calls) == 1


def test_settlement_timeout_remains_unknown(monkeypatch):
    sid = _seed("timeout")
    calls = []
    class Provider:
        async def transfer(self, **kwargs):
            calls.append(kwargs)
            raise httpx.ReadTimeout("synthetic timeout")
    _stub_prerequisites(monkeypatch, Provider())
    for _ in range(2):
        with SessionLocal() as db:
            result = asyncio.run(settlements.execute_settlement_instruction(db, db.get(SettlementInstruction, sid)))
            assert result.status == "unknown"
    with SessionLocal() as db:
        row = db.get(SettlementInstruction, sid)
        assert row.attempt_count == 1
        assert row.provider_operation_id
    assert len(calls) == 1
