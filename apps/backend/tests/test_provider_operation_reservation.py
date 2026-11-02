"""Provider reservation contract checks without network requests."""
import pytest
from services.provider_operation_reservation import payment_request_fingerprint
from services.payment_lifecycle import PaymentState, transition_payment, InvalidPaymentTransition


def test_fingerprint_independent_of_json_order():
    assert payment_request_fingerprint({"amount": "10.00", "currency": "LSL"}) == payment_request_fingerprint({"currency": "LSL", "amount": "10.00"})


def test_fingerprint_changes_for_different_payment():
    assert payment_request_fingerprint({"amount": "10.00"}) != payment_request_fingerprint({"amount": "20.00"})


def test_unknown_cannot_be_dispatched_again():
    with pytest.raises(InvalidPaymentTransition):
        transition_payment(PaymentState.UNKNOWN, PaymentState.DISPATCHED)


def test_dispatch_claim_uses_created_only_compare_and_swap():
    from unittest.mock import MagicMock
    from sqlalchemy.dialects import postgresql
    from services.provider_operation_reservation import claim_provider_dispatch

    db = MagicMock()
    db.execute.return_value.rowcount = 1
    assert claim_provider_dispatch(db, operation_id="op-id")
    stmt = db.execute.call_args.args[0]
    compiled = str(stmt.compile(dialect=postgresql.dialect()))
    assert "UPDATE provider_operations" in compiled
    assert "provider_operations.status" in compiled
    assert "provider_operations.id" in compiled
    db.execute.return_value.rowcount = 0
    assert not claim_provider_dispatch(db, operation_id="op-id")


def test_reservation_replay_returns_original_operation_without_second_record():
    from sqlalchemy import func, select
    from database.models import Application, IdempotencyRecord, Merchant, ProviderOperation
    from database.session import SessionLocal
    from services.provider_operation_reservation import (
        payment_request_fingerprint, reserve_provider_operation, claim_provider_dispatch,
    )

    with SessionLocal() as db:
        merchant = Merchant(name="Reservation test", slug="reservation-test")
        db.add(merchant)
        db.flush()
        application = Application(merchant_id=merchant.id, name="Reservation test", environment="test")
        db.add(application)
        db.flush()
        args = dict(
            application_id=application.id, merchant_id=merchant.id,
            provider="mpesa", operation_type="b2c",
            idempotency_key="single-payment-request",
            request_hash=payment_request_fingerprint({"amount": "10.00", "currency": "LSL"}),
            resource_type="payout", resource_id="test-resource",
            third_party_conversation_id="TEST-RESERVATION-ORIGINAL",
        )
        first, created = reserve_provider_operation(db, **args)
        assert created
        db.commit()
        original_id = first.id
        assert claim_provider_dispatch(db, operation_id=original_id)
        db.commit()

        # The replay carries a different proposed provider reference, but must
        # never create another operation or reset the original dispatch claim.
        replay, created = reserve_provider_operation(
            db, **{**args, "third_party_conversation_id": "TEST-RESERVATION-REPLAY"}
        )
        assert not created
        assert replay.id == original_id
        assert replay.third_party_conversation_id == "TEST-RESERVATION-ORIGINAL"
        assert replay.status == "dispatched"
        assert not claim_provider_dispatch(db, operation_id=original_id)
        assert db.scalar(select(func.count()).select_from(ProviderOperation)) == 1
        assert db.scalar(select(func.count()).select_from(IdempotencyRecord)) == 1
