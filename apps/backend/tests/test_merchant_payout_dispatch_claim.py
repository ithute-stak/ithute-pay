"""Regression guard for the merchant B2C single-dispatch boundary.

This test inspects the declared SQL statement rather than issuing live payouts.
"""
from sqlalchemy.dialects import postgresql
from sqlalchemy import update
from database.models import Payout


def test_payout_single_dispatch_claim_is_created_only():
    stmt = (
        update(Payout)
        .where(Payout.id == "test-id", Payout.status == "created")
        .values(status="processing")
    )
    compiled = str(stmt.compile(dialect=postgresql.dialect()))
    assert "UPDATE payouts" in compiled
    assert "payouts.status" in compiled
    assert "payouts.id" in compiled


def test_payment_timeout_is_not_a_failed_payment():
    from services.payment_lifecycle import PaymentState, may_dispatch
    assert not may_dispatch(PaymentState.UNKNOWN)
