"""Reversal amount reservations must not overrun the original settlement.

No provider API calls. Tests use disposable database rows only.
"""
import asyncio
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from database.models import Application, Merchant, ProviderTransaction, Reversal
from database.session import SessionLocal
from services.payments import reverse_transaction


def _seed(suffix: str, reversed_amount: Decimal | None = None):
    with SessionLocal() as db:
        merchant = Merchant(name="Reversal bound " + suffix, slug="reversal-bound-" + suffix)
        db.add(merchant); db.flush()
        app = Application(merchant_id=merchant.id, name="Reversal", environment="test")
        db.add(app); db.flush()
        transaction = ProviderTransaction(
            merchant_id=merchant.id, application_id=app.id, provider="mpesa",
            resource_type="payment_intent", resource_id="synthetic-" + suffix,
            direction="inbound", amount=Decimal("10.00"), currency="LSL",
            status="succeeded", transaction_reference="REV-" + suffix,
            third_party_conversation_id="REV-CONV-" + suffix,
            provider_transaction_id="CONFIRMED-" + suffix,
        )
        db.add(transaction); db.flush()
        if reversed_amount is not None:
            db.add(Reversal(
                public_id="prior-reversal-" + suffix, merchant_id=merchant.id,
                application_id=app.id, provider_transaction_id=transaction.id,
                amount=reversed_amount, reason="previous provider attempt",
                status="unknown",
            ))
        db.commit()
        return transaction.id, merchant.id, app.id


@pytest.mark.parametrize("value", [Decimal("0"), Decimal("-1"), Decimal("10.01")])
def test_reject_invalid_reversal_amount_before_provider_call(value):
    tx_id, merchant, app = _seed("invalid-" + str(value).replace(".", "-"))
    with SessionLocal() as db, patch("services.payments.get_provider") as provider:
        tx = db.get(ProviderTransaction, tx_id)
        with pytest.raises(HTTPException) as err:
            asyncio.run(reverse_transaction(db, transaction=tx, application_id=app,
                                            merchant_id=merchant, amount=value, reason="test"))
        assert err.value.status_code == 409
        provider.assert_not_called()


def test_prior_unknown_reservation_blocks_aggregate_overrun():
    tx_id, merchant, app = _seed("reserved", Decimal("7.00"))
    with SessionLocal() as db, patch("services.payments.get_provider") as provider:
        tx = db.get(ProviderTransaction, tx_id)
        with pytest.raises(HTTPException) as err:
            asyncio.run(reverse_transaction(db, transaction=tx, application_id=app,
                                            merchant_id=merchant, amount=Decimal("4.00"), reason="test"))
        assert err.value.status_code == 409
        provider.assert_not_called()
        assert len(db.scalars(select(Reversal).where(
            Reversal.provider_transaction_id == tx_id
        )).all()) == 1


def test_prior_processing_reservation_blocks_second_full_reversal():
    tx_id, merchant, app = _seed("processing", Decimal("10.00"))
    with SessionLocal() as db:
        row = db.scalar(select(Reversal).where(Reversal.provider_transaction_id == tx_id))
        row.status = "processing"
        db.commit()
    with SessionLocal() as db, patch("services.payments.get_provider") as provider:
        with pytest.raises(HTTPException) as err:
            asyncio.run(reverse_transaction(db, transaction=db.get(ProviderTransaction, tx_id),
                                            application_id=app, merchant_id=merchant,
                                            amount=None, reason="test"))
        assert err.value.status_code == 409
        provider.assert_not_called()
