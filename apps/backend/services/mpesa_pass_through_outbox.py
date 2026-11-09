"""Atomic, non-dispatching reservation of M-Pesa pass-through movements.

A reservation only persists a stable provider-facing reference and amount.
This module NEVER sends funds, creates provider operations, or authenticates
Vodacom callbacks. Live dispatch must be added behind separately reviewed
merchant, operator, provider and regulatory gates.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models.mpesa_pass_through_outbox import MpesaPassThroughOperationIntent
from services.mpesa_pass_through_lifecycle import TransactionError
from services.mpesa_pass_through_store import begin_record_leg, find_owned


def reserve_operation(
    db: Session, *, merchant_id: str, application_id: str,
    transaction_id: str, leg: str, reference: str,
) -> MpesaPassThroughOperationIntent:
    """Call inside a transaction; caller commits reservation and state together.

    PostgreSQL SELECT FOR UPDATE serializes callers for one transaction.
    Database unique constraints also reject different attempts across workers.
    Do not dispatch externally before the database transaction commits.
    """
    if leg not in {"funding", "onward", "refund"}:
        raise TransactionError("Unknown provider movement")
    if not reference or len(reference) > 80 or not reference.isascii():
        raise TransactionError("Invalid provider reference")
    row = find_owned(db, merchant_id=merchant_id, application_id=application_id,
                     record_id=transaction_id, for_update=True)
    if row is None:
        raise TransactionError("Transaction not found in authorized scope")

    existing = db.scalar(select(MpesaPassThroughOperationIntent).where(
        MpesaPassThroughOperationIntent.transaction_id == row.id,
        MpesaPassThroughOperationIntent.leg == leg,
    ))
    if existing is not None:
        if existing.reference != reference:
            raise TransactionError("Conflicting repeat operation; reconcile existing reference")
        return existing

    # begin_record_leg verifies funding succeeded before onward, and prevents
    # refunds while a beneficiary payout is processing or unknown.
    begin_record_leg(
        db, merchant_id=merchant_id, application_id=application_id,
        record_id=row.id, leg=leg, reference=reference,
    )
    amount: Decimal = row.funding_amount if leg in {"funding", "refund"} else row.onward_amount
    intent = MpesaPassThroughOperationIntent(
        transaction_id=row.id, merchant_id=merchant_id,
        application_id=application_id, leg=leg, reference=reference,
        amount=amount, currency=row.currency, provider="mpesa", state="reserved",
    )
    db.add(intent)
    db.flush()
    return intent


def list_reserved_for_reconciliation(db: Session, *, limit: int = 100):
    """Diagnostic only, for operators to compare against provider evidence.

    Deliberately does NOT hand records to a live payment dispatcher.
    A reserved operation after a crash is an UNKNOWN outcome until reconciled,
    not an invitation to submit again.
    """
    if not 1 <= limit <= 500:
        raise ValueError("Invalid limit")
    return db.scalars(
        select(MpesaPassThroughOperationIntent)
        .where(MpesaPassThroughOperationIntent.state == "reserved")
        .order_by(MpesaPassThroughOperationIntent.created_at,
                  MpesaPassThroughOperationIntent.id)
        .limit(limit)
    ).all()
