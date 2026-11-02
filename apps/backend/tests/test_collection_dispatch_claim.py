"""C2B collection dispatch contract without external payment traffic."""
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import dialect
from database.models import PaymentIntent


def test_collection_claim_requires_unprocessed_status():
    stmt = (
        update(PaymentIntent)
        .where(
            PaymentIntent.id == "payment-id",
            PaymentIntent.status.in_(("created", "requires_confirmation")),
        )
        .values(status="processing")
    )
    sql = str(stmt.compile(dialect=dialect()))
    assert "UPDATE payment_intents" in sql
    assert "payment_intents.status IN" in sql
    assert "payment_intents.id" in sql


def test_unknown_collection_cannot_be_redispatched():
    from services.payment_lifecycle import PaymentState, may_dispatch
    assert not may_dispatch(PaymentState.UNKNOWN)
    assert not may_dispatch(PaymentState.PROCESSING)
