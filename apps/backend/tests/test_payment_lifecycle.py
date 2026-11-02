import pytest

from services.payment_lifecycle import (
    InvalidPaymentTransition, PaymentState, may_dispatch, transition_payment,
)


def test_normal_payment_lifecycle():
    state = transition_payment("created", "dispatched")
    state = transition_payment(state, "processing")
    assert transition_payment(state, "succeeded") == PaymentState.SUCCEEDED


def test_unknown_outcome_cannot_be_retried_or_resolved_without_reconciliation():
    unknown = transition_payment("dispatched", "unknown")
    assert not may_dispatch(unknown)
    with pytest.raises(InvalidPaymentTransition, match="reconciliation"):
        transition_payment(unknown, "failed")
    with pytest.raises(InvalidPaymentTransition, match="reconciliation"):
        transition_payment(unknown, "succeeded")
    assert transition_payment(unknown, "succeeded", reconciled=True) == PaymentState.SUCCEEDED


def test_terminal_states_reject_second_disbursement():
    assert not may_dispatch("succeeded")
    assert not may_dispatch("failed")
    with pytest.raises(InvalidPaymentTransition):
        transition_payment("succeeded", "dispatched")
    with pytest.raises(InvalidPaymentTransition):
        transition_payment("failed", "processing")


def test_idempotent_state_repeat():
    assert transition_payment("processing", "processing") == PaymentState.PROCESSING
