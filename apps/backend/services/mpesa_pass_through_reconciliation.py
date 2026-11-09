"""Internal reconciliation of *authenticated provider QUERY* observations.

This is not a callback endpoint and does not fetch provider data itself.
Only a trusted provider-query integration may call it. The function verifies
every field against an existing outbox reservation, changes one leg, updates
the outbox reconciliation status and journals verified outgoing movements
inside the same caller-controlled SQL transaction. It never dispatches money.

Missing query fields, conflicting transaction IDs or unexpected beneficiaries
fail closed; no journal or fee may be recognized from an unverified response.
"""
from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from database.models.mpesa_pass_through import MpesaPassThroughTransaction
from database.models.mpesa_pass_through_outbox import MpesaPassThroughOperationIntent
from services.mpesa_pass_through_accounting import post_verified_outgoing
from services.mpesa_pass_through_evidence import (
    ExpectedMovement, ProviderQueryObservation, validate_provider_query,
)
from services.mpesa_pass_through_lifecycle import TransactionError
from services.mpesa_pass_through_store import find_owned, record_verified_evidence


def reconcile_authenticated_query(
    db: Session, *, merchant_id: str, application_id: str,
    transaction_id: str, leg: str,
    source_shortcode: str, destination: str,
    observation: ProviderQueryObservation,
) -> str:
    """Trusted backend only; source and destination MUST be server-owned settings.

    Never forward tenant-supplied shortcodes, phone numbers or provider JSON as
    the expected account identity. The caller must authenticate the actual
    Vodacom query response and its credential scope before invoking this.
    On any error, roll back the entire SQL transaction.
    """
    if leg not in {"funding", "onward", "refund"}:
        raise TransactionError("Unknown pass-through movement")
    row = find_owned(db, merchant_id=merchant_id, application_id=application_id,
                     record_id=transaction_id, for_update=True)
    if row is None:
        raise TransactionError("Transaction outside authorized tenant scope")
    intent = db.scalar(select(MpesaPassThroughOperationIntent).where(
        MpesaPassThroughOperationIntent.transaction_id == row.id,
        MpesaPassThroughOperationIntent.merchant_id == merchant_id,
        MpesaPassThroughOperationIntent.application_id == application_id,
        MpesaPassThroughOperationIntent.leg == leg,
    ).with_for_update())
    if intent is None or intent.provider != "mpesa":
        raise TransactionError("No approved reserved operation for movement")
    if (intent.currency != row.currency or
            intent.amount != (row.onward_amount if leg == "onward" else row.funding_amount)):
        raise TransactionError("Reserved operation differs from immutable quote")
    expected = ExpectedMovement(
        reference=intent.reference, amount=intent.amount, currency=intent.currency,
        source_shortcode=source_shortcode, destination=destination,
    )
    attested = validate_provider_query(expected, observation)
    if attested.transaction_id:
        # Neither another payment nor another leg of this same payment may
        # silently reuse a provider transaction identifier.
        collisions = db.scalars(select(MpesaPassThroughTransaction).where(
            or_(
                MpesaPassThroughTransaction.funding_provider_id == attested.transaction_id,
                MpesaPassThroughTransaction.onward_provider_id == attested.transaction_id,
                MpesaPassThroughTransaction.refund_provider_id == attested.transaction_id,
            )
        )).all()
        for other in collisions:
            if other.id != row.id or getattr(other, leg + "_provider_id") != attested.transaction_id:
                raise TransactionError("Provider identifier already used for another movement")
    record_verified_evidence(
        db, merchant_id=merchant_id, application_id=application_id, record_id=row.id,
        leg=leg, reference=intent.reference, status=attested.outcome,
        provider_transaction_id=attested.transaction_id,
        evidence=attested.canonical_evidence,
    )
    intent.state = "closed" if attested.outcome in {"succeeded", "failed"} else "needs_reconciliation"
    # For successfully completed outgoing movements, post exactly once using
    # the existing ledger. No fee is earned while beneficiary status is unknown.
    if row.direction == "outgoing":
        post_verified_outgoing(
            db, merchant_id=merchant_id, application_id=application_id,
            transaction_id=row.id,
        )
    else:
        # Incoming pass-through accounting has not been certified; never
        # accept an incoming movement as confirmed in this adapter.
        raise TransactionError("Incoming pass-through reconciliation not yet certified")
    db.flush()
    return attested.outcome
