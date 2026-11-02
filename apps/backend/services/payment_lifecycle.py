"""Provider-neutral payment lifecycle rules.

Never infer payment failure from a transport exception. In particular,
UNKNOWN payment outcomes require provider reconciliation before a retry.
This module has no provider network I/O or database side effects.
"""
from __future__ import annotations

from enum import Enum


class PaymentState(str, Enum):
    CREATED = "created"
    DISPATCHED = "dispatched"
    PROCESSING = "processing"
    UNKNOWN = "unknown"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class InvalidPaymentTransition(ValueError):
    pass


_ALLOWED = {
    PaymentState.CREATED: frozenset({PaymentState.DISPATCHED, PaymentState.FAILED}),
    PaymentState.DISPATCHED: frozenset({PaymentState.PROCESSING, PaymentState.UNKNOWN, PaymentState.SUCCEEDED, PaymentState.FAILED}),
    PaymentState.PROCESSING: frozenset({PaymentState.UNKNOWN, PaymentState.SUCCEEDED, PaymentState.FAILED}),
    PaymentState.UNKNOWN: frozenset({PaymentState.PROCESSING, PaymentState.SUCCEEDED, PaymentState.FAILED}),
    PaymentState.SUCCEEDED: frozenset(),
    PaymentState.FAILED: frozenset(),
}


def transition_payment(current: PaymentState | str, target: PaymentState | str, *, reconciled: bool = False) -> PaymentState:
    before = PaymentState(current)
    after = PaymentState(target)
    if after == before:
        return before
    if after not in _ALLOWED[before]:
        raise InvalidPaymentTransition(f"Invalid payment transition: {before.value} -> {after.value}")
    if before == PaymentState.UNKNOWN and after != PaymentState.UNKNOWN and not reconciled:
        raise InvalidPaymentTransition("An unknown outcome requires verified provider reconciliation")
    return after


def may_dispatch(state: PaymentState | str) -> bool:
    """Only new operations can be dispatched. Retrying UNKNOWN is unsafe."""
    return PaymentState(state) == PaymentState.CREATED
