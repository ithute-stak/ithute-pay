"""Fault-injection tests: provider reconciliation must never repeat money movement.

These tests operate entirely on local models/mocks. No M-PESA network calls.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from database.models import ProviderCallbackLog
from services.payment_lifecycle import PaymentState, InvalidPaymentTransition, transition_payment
from services.payments import apply_provider_result
from services.provider_operations import apply_operation_result


@pytest.mark.parametrize("status", ["dispatched", "processing", "unknown", "succeeded", "failed"])
def test_no_resubmission_after_first_dispatch(status):
    from services.payment_lifecycle import may_dispatch
    assert not may_dispatch(status)


def test_timeout_then_late_success_requires_reconciliation():
    state = transition_payment("created", "dispatched")
    state = transition_payment(state, "unknown")
    with pytest.raises(InvalidPaymentTransition):
        transition_payment(state, "succeeded")
    assert transition_payment(state, "succeeded", reconciled=True) == PaymentState.SUCCEEDED


def test_out_of_order_query_does_not_downgrade_success():
    db = MagicMock()
    tx = SimpleNamespace(status="succeeded", confirmed_at=object())
    incoming = SimpleNamespace(status="failed")
    apply_provider_result(db, transaction=tx, result=incoming)
    assert tx.status == "succeeded"
    db.add.assert_not_called()


def test_out_of_order_operation_callback_does_not_downgrade_success():
    db = MagicMock()
    operation = SimpleNamespace(status="succeeded")
    incoming = SimpleNamespace(status="unknown")
    apply_operation_result(db, operation, incoming)
    assert operation.status == "succeeded"
    db.add.assert_not_called()


def test_duplicate_callback_hash_is_unique_within_provider_and_type():
    unique = next(c for c in ProviderCallbackLog.__table__.constraints if getattr(c,"name",None)=="uq_provider_callback_payload")
    assert set(unique.columns.keys()) == {"provider", "callback_type", "payload_hash"}
