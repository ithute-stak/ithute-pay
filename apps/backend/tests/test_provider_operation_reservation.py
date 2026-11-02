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
