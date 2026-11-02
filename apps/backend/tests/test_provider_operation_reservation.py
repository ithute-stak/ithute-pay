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
