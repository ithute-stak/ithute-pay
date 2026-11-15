"""Fail closed when a recovered provider success has inconsistent ledger funding."""
import asyncio
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from database.models import Application, Merchant, Payout, ProviderOperation
from database.session import SessionLocal
from integrations.base import ProviderResult
from services import payments
from services.direct_funding_amounts import verified_direct_funding_amount
from services.direct_funding_recovery import reconcile_direct_funding_payout


@pytest.mark.parametrize("fee,total", [
    ("10.00", "1010.01"), ("10.01", "1010.00"),
    ("", "1010.00"), ("NaN", "1010.00"),
    ("10.00", "Infinity"), ("-1.00", "999.00"),
    ("10.001", "1010.001"),
])
def test_bad_amount_evidence_rejected_without_database_access(fee, total):
    payout = SimpleNamespace(amount=Decimal("1000.00"), metadata_json={
        "funding_mode": "direct_mpesa", "gateway_fee_amount": fee,
        "funding_debit_amount": total,
    })
    with pytest.raises(HTTPException) as error:
        verified_direct_funding_amount(payout)
    assert error.value.status_code == 409


def seed(suffix, *, fee="10.00", total="1010.00"):
    with SessionLocal() as db:
        merchant = Merchant(name="Recovery amount " + suffix, slug="recovery-amount-" + suffix)
        db.add(merchant); db.flush()
        app = Application(merchant_id=merchant.id, name="Recovery amount", environment="test")
        db.add(app); db.flush()
        payout = Payout(
            public_id="recovery-amount-" + suffix, merchant_id=merchant.id,
            application_id=app.id, amount=Decimal("1000.00"),
            currency="LSL", provider="mpesa", destination_phone="26650000000",
            reference="recovery-amount-" + suffix, status="funding_unknown",
            metadata_json={"funding_mode": "direct_mpesa",
                           "funding_account_reference": "synthetic",
                           "funding_debit_amount": total, "gateway_fee_amount": fee},
        )
        db.add(payout); db.flush()
        operation = ProviderOperation(
            merchant_id=merchant.id, application_id=app.id,
            provider="mpesa", operation_type="payout.direct_funding",
            resource_type="payout", resource_id=payout.id, status="succeeded",
            third_party_conversation_id="AMOUNT-REC-" + suffix,
        )
        db.add(operation); db.flush()
        payout.metadata_json = {**payout.metadata_json, "direct_funding_operation_id": operation.id}
        db.commit()
        return payout.id, operation.id


def test_recovery_worker_blocks_invalid_credit_before_account_lookup(monkeypatch):
    payout_id, operation_id = seed("mismatch", fee="10.00", total="1020.00")
    def forbidden(*args, **kwargs):
        pytest.fail("invalid funding cannot credit or query the account")
    monkeypatch.setattr("services.direct_funding_recovery.funding_account", forbidden)
    monkeypatch.setattr("services.direct_funding_recovery.credit_direct_funding", forbidden)
    monkeypatch.setattr("services.direct_funding_recovery.book_direct_company_funding", forbidden)
    with SessionLocal() as db:
        payout = db.get(Payout, payout_id)
        operation = db.get(ProviderOperation, operation_id)
        with pytest.raises(HTTPException) as exc:
            asyncio.run(reconcile_direct_funding_payout(db, payout, operation))
        assert exc.value.status_code == 409
        assert payout.status == "funding_unknown"


def test_initial_confirmation_blocks_invalid_credit_before_account_lookup(monkeypatch):
    payout_id, operation_id = seed("callback", fee="10.00", total="999.00")
    def forbidden(*args, **kwargs):
        pytest.fail("invalid funding cannot credit or query the account")
    monkeypatch.setattr(payments, "_payout_funding_account", forbidden)
    monkeypatch.setattr(payments, "credit_direct_funding", forbidden)
    monkeypatch.setattr(payments, "book_direct_company_funding", forbidden)
    with SessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(payments.finalize_direct_funding_operation(
                db, db.get(ProviderOperation, operation_id),
                ProviderResult(accepted=True, status="succeeded"),
            ))
        assert exc.value.status_code == 409
        assert db.get(Payout, payout_id).status == "funding_unknown"


def test_exact_snapshot_accepted():
    payout = SimpleNamespace(amount=Decimal("1000.00"), metadata_json={
        "funding_mode": "direct_mpesa",
        "gateway_fee_amount": "10.00",
        "funding_debit_amount": "1010.00",
    })
    assert verified_direct_funding_amount(payout) == Decimal("1010.00")
