"""Late funding confirmation can hand off ONE payout, never duplicate funds."""
import asyncio
import hashlib
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from database.models import Application, Merchant, Payout, ProviderOperation, ProviderTransaction
from database.session import SessionLocal
from services import payments
from services.direct_funding_recovery import reconcile_direct_funding_payout


def seed(suffix: str, funding_status: str = "succeeded"):
    with SessionLocal() as db:
        merchant = Merchant(name="Recovery handoff " + suffix, slug="recovery-handoff-" + suffix)
        db.add(merchant); db.flush()
        app = Application(merchant_id=merchant.id, name="Recovery handoff", environment="test")
        db.add(app); db.flush()
        payout = Payout(
            public_id="recovery-handoff-" + suffix, merchant_id=merchant.id,
            application_id=app.id, amount=Decimal("10.00"), currency="LSL",
            provider="mpesa", destination_phone="26650000000",
            reference="recovery-" + suffix, status="funding_unknown",
            metadata_json={"funding_mode": "direct_mpesa", "funding_account_reference": "company",
                           "gateway_fee_amount": "0.10", "funding_debit_amount": "10.10"},
        )
        db.add(payout); db.flush()
        operation = ProviderOperation(
            merchant_id=merchant.id, application_id=app.id, provider="mpesa",
            operation_type="payout.direct_funding", resource_type="payout",
            resource_id=payout.id, status=funding_status,
            third_party_conversation_id="REC-HANDOFF-" + suffix,
        )
        db.add(operation); db.flush()
        metadata = dict(payout.metadata_json)
        metadata["direct_funding_operation_id"] = operation.id
        payout.metadata_json = metadata
        tx = ProviderTransaction(
            merchant_id=merchant.id, application_id=app.id,
            resource_type="payout", resource_id=payout.id, provider="mpesa",
            direction="outbound", amount=Decimal("10.00"), currency="LSL",
            status="created", transaction_reference="RH-" + hashlib.sha256(suffix.encode()).hexdigest()[:12],
            third_party_conversation_id="RH-CONV-" + suffix,
        )
        db.add(tx); db.commit()
        return payout.id, tx.id, operation.id


def _stub(monkeypatch, provider):
    monkeypatch.setattr(payments, "_payout_funding_account",
                        lambda *args, **kwargs: SimpleNamespace(id="synthetic"))
    monkeypatch.setattr(payments, "calculate_fee_details",
                        lambda *args: SimpleNamespace(amount=Decimal("0.10"), payer="merchant", source="test"))
    monkeypatch.setattr(payments, "reserve_payout", lambda *args, **kwargs: None)
    monkeypatch.setattr(payments, "get_provider", lambda *args, **kwargs: provider)
    monkeypatch.setattr(payments, "require_provider_capability", lambda *args: None)
    def apply(db, *, transaction, result):
        transaction.status = result.status
        db.add(transaction)
    monkeypatch.setattr(payments, "apply_provider_result", apply)


def test_late_confirmed_funding_dispatches_one_payout(monkeypatch):
    payout_id, tx_id, _ = seed("confirmed")
    calls = []
    class Provider:
        async def payout(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(status="processing")
    _stub(monkeypatch, Provider())
    for _ in range(2):
        with SessionLocal() as db:
            result = asyncio.run(payments._execute_funded_payout(
                db, db.get(Payout, payout_id), db.get(ProviderTransaction, tx_id)))
            assert result.status == "processing"
    assert len(calls) == 1
    with SessionLocal() as db:
        assert db.get(Payout, payout_id).metadata_json["funding_reservation_transaction_id"] == tx_id


@pytest.mark.parametrize("status", ["processing", "unknown", "failed"])
def test_unconfirmed_funding_cannot_dispatch(monkeypatch, status):
    payout_id, tx_id, _ = seed("unconfirmed-" + status, funding_status=status)
    calls = []
    class Provider:
        async def payout(self, **kwargs):
            calls.append(kwargs)
    _stub(monkeypatch, Provider())
    with SessionLocal() as db:
        with pytest.raises(Exception, match="Direct funding is not confirmed"):
            asyncio.run(payments._execute_funded_payout(
                db, db.get(Payout, payout_id), db.get(ProviderTransaction, tx_id)))
    assert not calls


def test_recovery_worker_rejects_unlinked_funding_operation_before_query(monkeypatch):
    payout_id, _, operation_id = seed("mismatch", funding_status="unknown")
    with SessionLocal() as db:
        payout = db.get(Payout, payout_id)
        operation = db.get(ProviderOperation, operation_id)
        payout.metadata_json = {**payout.metadata_json, "direct_funding_operation_id": "incorrect"}
        with pytest.raises(ValueError, match="does not match payout scope"):
            asyncio.run(reconcile_direct_funding_payout(db, payout, operation))
        assert not db.new


def test_completed_handoff_never_retries(monkeypatch):
    payout_id, tx_id, _ = seed("dispatched")
    with SessionLocal() as db:
        payout = db.get(Payout, payout_id)
        payout.status = "unknown"
        db.commit()
    calls = []
    class Provider:
        async def payout(self, **kwargs):
            calls.append(kwargs)
    _stub(monkeypatch, Provider())
    with SessionLocal() as db:
        result = asyncio.run(payments._execute_funded_payout(
            db, db.get(Payout, payout_id), db.get(ProviderTransaction, tx_id)))
        assert result.status == "unknown"
    assert not calls
