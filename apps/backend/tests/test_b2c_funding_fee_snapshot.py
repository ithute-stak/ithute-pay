"""Direct-funded B2C payment must preserve approved principal and fee snapshot."""
import asyncio
import hashlib
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from database.models import Application, Merchant, Payout, ProviderOperation, ProviderTransaction
from database.session import SessionLocal
from services import payments


def seed(suffix: str, *, funded_fee="10.00", funded_total="1010.00"):
    with SessionLocal() as db:
        merchant = Merchant(name="B2C snapshot " + suffix, slug="b2c-snapshot-" + suffix)
        db.add(merchant); db.flush()
        app = Application(merchant_id=merchant.id, name="B2C snapshot", environment="test")
        db.add(app); db.flush()
        payout = Payout(
            public_id="snap-" + suffix, application_id=app.id, merchant_id=merchant.id,
            amount=Decimal("1000.00"), currency="LSL", provider="mpesa",
            destination_phone="26650000000", reference="snap-" + suffix,
            status="funding_unknown",
            metadata_json={"funding_mode": "direct_mpesa",
                           "gateway_fee_amount": funded_fee,
                           "funding_debit_amount": funded_total},
        )
        db.add(payout); db.flush()
        operation = ProviderOperation(
            application_id=app.id, merchant_id=merchant.id, provider="mpesa",
            operation_type="payout.direct_funding", resource_type="payout",
            resource_id=payout.id, status="succeeded",
            third_party_conversation_id="SNAP-FUND-" + suffix,
        )
        db.add(operation); db.flush()
        payout.metadata_json = {**payout.metadata_json, "direct_funding_operation_id": operation.id}
        tx = ProviderTransaction(
            application_id=app.id, merchant_id=merchant.id, provider="mpesa",
            resource_type="payout", resource_id=payout.id, direction="outbound",
            amount=Decimal("1000.00"), currency="LSL", status="created",
            transaction_reference="SN-" + hashlib.sha256(suffix.encode()).hexdigest()[:12],
            third_party_conversation_id="SNAP-TX-" + suffix,
        )
        db.add(tx); db.commit()
        return payout.id, tx.id


def preflight(monkeypatch, calls):
    monkeypatch.setattr(payments, "_payout_funding_account",
                        lambda *args, **kwargs: SimpleNamespace(id="synthetic"))
    monkeypatch.setattr(payments, "calculate_fee_details",
                        lambda *args: SimpleNamespace(amount=Decimal("10.00"), payer="merchant", source="test"))
    def reserve(*args, **kwargs):
        calls.append("reserve")
    monkeypatch.setattr(payments, "reserve_payout", reserve)


@pytest.mark.parametrize("fee,total", [
    ("10.01", "1010.01"), ("10.00", "1009.99"),
    ("NaN", "1010.00"), ("10.00", "Infinity"),
    ("", "1010.00"), ("10.00", ""),
])
def test_disagreeing_fee_or_funding_total_blocks_b2c_without_reservation(monkeypatch, fee, total):
    suffix = "invalid-" + str(len(fee)) + "-" + str(len(total)) + "-" + str(sum(ord(x) for x in fee + total))
    payout_id, tx_id = seed(suffix, funded_fee=fee, funded_total=total)
    calls = []
    preflight(monkeypatch, calls)
    with SessionLocal() as db:
        payout = db.get(Payout, payout_id)
        tx = db.get(ProviderTransaction, tx_id)
        with pytest.raises(HTTPException) as exc:
            asyncio.run(payments._execute_funded_payout(db, payout, tx))
        assert exc.value.status_code == 409
        assert not calls
        db.refresh(payout)
        assert payout.status == "funding_unknown"


def test_original_fee_snapshot_allows_single_claim(monkeypatch):
    payout_id, tx_id = seed("valid")
    calls = []
    preflight(monkeypatch, calls)
    class Provider:
        async def payout(self, **kwargs):
            calls.append("provider")
            return SimpleNamespace(status="processing")
    monkeypatch.setattr(payments, "get_provider", lambda *args, **kwargs: Provider())
    monkeypatch.setattr(payments, "require_provider_capability", lambda *args, **kwargs: None)
    def apply(db, *, transaction, result):
        transaction.status = result.status
        db.add(transaction)
    monkeypatch.setattr(payments, "apply_provider_result", apply)
    for _ in range(2):
        with SessionLocal() as db:
            payout = db.get(Payout, payout_id)
            tx = db.get(ProviderTransaction, tx_id)
            assert asyncio.run(payments._execute_funded_payout(db, payout, tx)).status == "processing"
    assert calls == ["reserve", "provider"]
