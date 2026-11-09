"""Database tests for durable pass-through quotes and leg state.

No real provider requests or money movement are performed.
"""
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import Application, Merchant, MpesaPassThroughTransaction
from database.session import SessionLocal
from services.mpesa_pass_through_lifecycle import TransactionError
from services.mpesa_pass_through_quotes import quote
from services.mpesa_pass_through_store import (
    begin_record_leg, create_quote_record, find_owned, load_lifecycle, record_verified_evidence,
)


def setup_identity(db: Session, suffix: str):
    merchant = Merchant(name="Tenant " + suffix, slug="pt-test-" + suffix)
    db.add(merchant)
    db.flush()
    app = Application(merchant_id=merchant.id, name="Pass Through " + suffix, environment="test")
    db.add(app)
    db.flush()
    return merchant.id, app.id


def quote_for(merchant: str):
    return quote(tenant_id=merchant, direction="outgoing", principal="1000.00", approved=True)


def test_quote_persists_across_database_sessions():
    with SessionLocal() as db:
        tenant, app = setup_identity(db, "persist")
        row = create_quote_record(db, merchant_id=tenant, application_id=app,
                                  idempotency_key="operation-1", request={"amount": "1000.00"},
                                  quote=quote_for(tenant))
        record_id = row.id
        db.commit()
    with SessionLocal() as db:
        persisted = find_owned(db, merchant_id=tenant, application_id=app, record_id=record_id)
        assert persisted is not None
        assert persisted.funding_amount == Decimal("1010.00")
        assert persisted.platform_fee == Decimal("10.00")
        assert persisted.funding_status == "not_started"


def test_idempotent_repeat_returns_original():
    with SessionLocal() as db:
        tenant, app = setup_identity(db, "idempotent")
        args = dict(merchant_id=tenant, application_id=app, idempotency_key="same",
                    request={"amount": "1000"}, quote=quote_for(tenant))
        first = create_quote_record(db, **args)
        second = create_quote_record(db, **args)
        assert first.id == second.id
        assert len(db.scalars(select(MpesaPassThroughTransaction)).all()) == 1


def test_conflicting_idempotency_is_rejected():
    with SessionLocal() as db:
        tenant, app = setup_identity(db, "conflict")
        create_quote_record(db, merchant_id=tenant, application_id=app,
                            idempotency_key="same", request={"amount": "1000"},
                            quote=quote_for(tenant))
        with pytest.raises(TransactionError):
            create_quote_record(db, merchant_id=tenant, application_id=app,
                                idempotency_key="same", request={"amount": "1001"},
                                quote=quote_for(tenant))


def test_other_tenant_cannot_see_or_transition_payment():
    with SessionLocal() as db:
        tenant, app = setup_identity(db, "owner")
        other, other_app = setup_identity(db, "other")
        row = create_quote_record(db, merchant_id=tenant, application_id=app,
                                  idempotency_key="ref", request={"amount": "1000"},
                                  quote=quote_for(tenant))
        assert find_owned(db, merchant_id=other, application_id=other_app, record_id=row.id) is None
        with pytest.raises(TransactionError):
            begin_record_leg(db, merchant_id=other, application_id=other_app,
                             record_id=row.id, leg="funding", reference="f-1")


def test_funding_then_payout_stores_verified_evidence():
    with SessionLocal() as db:
        tenant, app = setup_identity(db, "legs")
        row = create_quote_record(db, merchant_id=tenant, application_id=app,
                                  idempotency_key="operation", request={"amount": "1000"},
                                  quote=quote_for(tenant))
        record_id = row.id
        begin_record_leg(db, merchant_id=tenant, application_id=app,
                         record_id=record_id, leg="funding", reference="fund")
        record_verified_evidence(db, merchant_id=tenant, application_id=app,
                                 record_id=record_id, leg="funding", reference="fund",
                                 status="succeeded", provider_transaction_id="vodacom-fund",
                                 evidence=b"confirmed funding")
        assert load_lifecycle(row).fee_earned == 0
        assert load_lifecycle(row).settlement_liability == Decimal("1010.00")
        begin_record_leg(db, merchant_id=tenant, application_id=app,
                         record_id=record_id, leg="onward", reference="client")
        record_verified_evidence(db, merchant_id=tenant, application_id=app,
                                 record_id=record_id, leg="onward", reference="client",
                                 status="succeeded", provider_transaction_id="vodacom-client",
                                 evidence=b"confirmed payout")
        assert load_lifecycle(row).fee_earned == Decimal("10.00")
        assert load_lifecycle(row).settlement_liability == 0
        db.commit()
    with SessionLocal() as db:
        persisted = find_owned(db, merchant_id=tenant, application_id=app, record_id=record_id)
        assert load_lifecycle(persisted).complete


def test_uncertain_payout_cannot_be_repeated_or_refunded():
    with SessionLocal() as db:
        tenant, app = setup_identity(db, "unknown")
        row = create_quote_record(db, merchant_id=tenant, application_id=app,
                                  idempotency_key="operation", request={"amount": "1000"},
                                  quote=quote_for(tenant))
        args = dict(db=db, merchant_id=tenant, application_id=app, record_id=row.id)
        begin_record_leg(**args, leg="funding", reference="fund")
        record_verified_evidence(**args, leg="funding", reference="fund", status="succeeded",
                                 provider_transaction_id="tx-f", evidence=b"confirmed")
        begin_record_leg(**args, leg="onward", reference="pay")
        record_verified_evidence(**args, leg="onward", reference="pay", status="unknown",
                                 provider_transaction_id=None, evidence=b"timeout")
        with pytest.raises(TransactionError):
            begin_record_leg(**args, leg="onward", reference="pay-again")
        with pytest.raises(TransactionError):
            begin_record_leg(**args, leg="refund", reference="refund")


def test_quote_cannot_be_written_for_another_merchant():
    with SessionLocal() as db:
        tenant, app = setup_identity(db, "wrong")
        other, _ = setup_identity(db, "wrong-other")
        with pytest.raises(TransactionError):
            create_quote_record(db, merchant_id=tenant, application_id=app,
                                idempotency_key="fraud", request={"amount": "1000"},
                                quote=quote_for(other))
