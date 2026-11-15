"""Late direct-funding callbacks may not regress a dispatched B2C payout."""
import asyncio
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from database.models import Application, Merchant, Payout, ProviderOperation
from database.session import SessionLocal
from integrations.base import ProviderResult
from services import payments


def seed(suffix, *, payout_status="processing", operation_status="succeeded", linked=True):
    with SessionLocal() as db:
        merchant = Merchant(name="Callback safety " + suffix, slug="callback-safety-" + suffix)
        db.add(merchant); db.flush()
        app = Application(merchant_id=merchant.id, name="Callback safety", environment="test")
        db.add(app); db.flush()
        payout = Payout(
            public_id="cb-safe-" + suffix, merchant_id=merchant.id, application_id=app.id,
            amount=Decimal("1000.00"), currency="LSL", provider="mpesa",
            destination_phone="26650000000", reference="CB-" + suffix,
            status=payout_status, metadata_json={"funding_mode": "direct_mpesa",
                "funding_debit_amount": "1010.00", "gateway_fee_amount": "10.00"},
        )
        db.add(payout); db.flush()
        op = ProviderOperation(
            merchant_id=merchant.id, application_id=app.id, provider="mpesa",
            operation_type="payout.direct_funding", resource_type="payout",
            resource_id=payout.id, status=operation_status,
            third_party_conversation_id="CB-FND-" + suffix,
        )
        db.add(op); db.flush()
        payout.metadata_json = {**payout.metadata_json,
            "direct_funding_operation_id": op.id if linked else "wrong-operation"}
        db.commit()
        return payout.id, op.id


@pytest.mark.parametrize("payout_status", ["processing", "unknown", "succeeded"])
def test_stale_failure_cannot_downgrade_dispatched_payout(monkeypatch, payout_status):
    payout_id, operation_id = seed("late-" + payout_status, payout_status=payout_status)
    monkeypatch.setattr(payments, "credit_direct_funding",
                        lambda *args, **kwargs: pytest.fail("unexpected funding credit"))
    monkeypatch.setattr(payments, "book_direct_company_funding",
                        lambda *args, **kwargs: pytest.fail("unexpected journal posting"))
    monkeypatch.setattr(payments, "_execute_funded_payout",
                        lambda *args, **kwargs: pytest.fail("unexpected payout dispatch"))
    with SessionLocal() as db:
        payout = asyncio.run(payments.finalize_direct_funding_operation(
            db, db.get(ProviderOperation, operation_id),
            ProviderResult(accepted=False, status="failed", response_code="OLD-FAIL")
        ))
        assert payout.status == payout_status
        assert db.get(ProviderOperation, operation_id).status == "succeeded"


def test_unknown_callback_cannot_reopen_confirmed_failed_funding():
    payout_id, operation_id = seed("terminal-failed", payout_status="funding_unknown",
                                  operation_status="failed")
    with SessionLocal() as db:
        payout = asyncio.run(payments.finalize_direct_funding_operation(
            db, db.get(ProviderOperation, operation_id),
            ProviderResult(accepted=False, status="unknown", response_code="STALE")
        ))
        assert payout.status == "failed"
        assert db.get(ProviderOperation, operation_id).status == "failed"


def test_unlinked_operation_rejected_before_changes(monkeypatch):
    payout_id, operation_id = seed("unlinked", linked=False)
    with SessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(payments.finalize_direct_funding_operation(
                db, db.get(ProviderOperation, operation_id),
                ProviderResult(accepted=False, status="failed")
            ))
        assert exc.value.status_code == 409
        assert db.get(Payout, payout_id).status == "processing"
        assert db.get(ProviderOperation, operation_id).status == "succeeded"


def test_stale_failure_after_confirmed_funding_allows_only_original_handoff(monkeypatch):
    payout_id, operation_id = seed("late-before-handoff", payout_status="funding_unknown")
    calls = []
    monkeypatch.setattr(payments, "_payout_funding_account",
                        lambda *args, **kwargs: SimpleNamespace(id="isolated"))
    monkeypatch.setattr(payments, "credit_direct_funding",
                        lambda *args, **kwargs: calls.append("credit"))
    monkeypatch.setattr(payments, "book_direct_company_funding",
                        lambda *args, **kwargs: calls.append("journal"))
    monkeypatch.setattr(payments, "_payout_transaction",
                        lambda *args, **kwargs: object())
    async def handoff(db, payout, tx):
        calls.append("handoff")
        payout.status = "processing"
        db.add(payout); db.commit()
        return payout
    monkeypatch.setattr(payments, "_execute_funded_payout", handoff)
    with SessionLocal() as db:
        payout = asyncio.run(payments.finalize_direct_funding_operation(
            db, db.get(ProviderOperation, operation_id),
            ProviderResult(accepted=False, status="failed", response_code="STALE")
        ))
        assert payout.status == "processing"
    assert calls == ["credit", "journal", "handoff"]
