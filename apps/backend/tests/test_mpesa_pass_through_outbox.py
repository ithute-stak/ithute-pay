"""Tests outbox reservation durability and transaction-leg safety.

These tests never call a payment provider and never run against production.
"""
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from database.models import Application, Merchant, MpesaPassThroughOperationIntent
from database.session import SessionLocal
from services.mpesa_pass_through_lifecycle import TransactionError
from services.mpesa_pass_through_outbox import reserve_operation, list_reserved_for_reconciliation
from services.mpesa_pass_through_quotes import quote
from services.mpesa_pass_through_store import create_quote_record, record_verified_evidence


def setup(db, suffix):
    merchant = Merchant(name="PT " + suffix, slug="pt-outbox-" + suffix)
    db.add(merchant)
    db.flush()
    app = Application(merchant_id=merchant.id, name="Test " + suffix, environment="test")
    db.add(app)
    db.flush()
    q = quote(tenant_id=merchant.id, direction="outgoing",
              principal="1000.00", approved=True)
    tx = create_quote_record(db, merchant_id=merchant.id, application_id=app.id,
                             idempotency_key="tx-1", request={"amount": "1000.00"}, quote=q)
    return merchant.id, app.id, tx.id


def test_reservation_commits_with_leg_state():
    with SessionLocal() as db:
        merchant, app, tx = setup(db, "durable")
        item = reserve_operation(db, merchant_id=merchant, application_id=app,
                                 transaction_id=tx, leg="funding", reference="f-001")
        assert item.amount == Decimal("1010.00")
        db.commit()
    with SessionLocal() as db:
        saved = db.scalar(select(MpesaPassThroughOperationIntent).where(
            MpesaPassThroughOperationIntent.transaction_id == tx,
        ))
        assert saved.reference == "f-001"
        assert saved.state == "reserved"


def test_same_reference_replay_is_idempotent():
    with SessionLocal() as db:
        merchant, app, tx = setup(db, "replay")
        kw = dict(db=db, merchant_id=merchant, application_id=app,
                  transaction_id=tx, leg="funding", reference="f-002")
        a = reserve_operation(**kw)
        b = reserve_operation(**kw)
        assert a.id == b.id


def test_conflicting_reference_rejected():
    with SessionLocal() as db:
        merchant, app, tx = setup(db, "conflict")
        kw = dict(db=db, merchant_id=merchant, application_id=app, transaction_id=tx, leg="funding")
        reserve_operation(**kw, reference="f-003")
        with pytest.raises(TransactionError):
            reserve_operation(**kw, reference="f-004")


def test_unfunded_onward_cannot_be_reserved():
    with SessionLocal() as db:
        merchant, app, tx = setup(db, "unfunded")
        with pytest.raises(TransactionError):
            reserve_operation(db, merchant_id=merchant, application_id=app,
                              transaction_id=tx, leg="onward", reference="p-001")


def test_verified_funding_allows_one_onward_intent():
    with SessionLocal() as db:
        merchant, app, tx = setup(db, "funded")
        kw = dict(db=db, merchant_id=merchant, application_id=app, transaction_id=tx)
        reserve_operation(**kw, leg="funding", reference="f-005")
        record_verified_evidence(db, merchant_id=merchant, application_id=app,
                                 record_id=tx, leg="funding", reference="f-005",
                                 status="succeeded", provider_transaction_id="provider-f",
                                 evidence=b"externally verified funding proof")
        pay = reserve_operation(**kw, leg="onward", reference="p-005")
        assert pay.amount == Decimal("1000.00")
        assert len(db.scalars(select(MpesaPassThroughOperationIntent)).all()) == 2


def test_cannot_cross_tenant():
    with SessionLocal() as db:
        merchant, app, tx = setup(db, "owner")
        another, another_app, _ = setup(db, "stranger")
        with pytest.raises(TransactionError):
            reserve_operation(db, merchant_id=another, application_id=another_app,
                              transaction_id=tx, leg="funding", reference="forged")


def test_same_provider_reference_unique_across_transactions():
    with SessionLocal() as db:
        a, app_a, tx_a = setup(db, "unique-a")
        b, app_b, tx_b = setup(db, "unique-b")
        reserve_operation(db, merchant_id=a, application_id=app_a,
                          transaction_id=tx_a, leg="funding", reference="same-ref")
        with pytest.raises(IntegrityError):
            reserve_operation(db, merchant_id=b, application_id=app_b,
                              transaction_id=tx_b, leg="funding", reference="same-ref")


def test_no_automatic_dispatch_or_provider_operation():
    with SessionLocal() as db:
        merchant, app, tx = setup(db, "no-dispatch")
        reserve_operation(db, merchant_id=merchant, application_id=app,
                          transaction_id=tx, leg="funding", reference="f-008")
        items = list_reserved_for_reconciliation(db)
        assert len(items) == 1
        assert items[0].provider_operation_id is None
        assert items[0].submitted_at is None
