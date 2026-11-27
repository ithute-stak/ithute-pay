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

    if (row.quote_snapshot or {}).get("reversal_holds"):
        raise TransactionError("Transaction held for provider reversal investigation")

    # Incoming funding may be net of a non-refundable provider charge.
    # Never reserve a gross refund until actual fee recovery and refund
    # responsibility have been independently established.
    if row.direction == "incoming" and leg == "refund":
        raise TransactionError("Incoming refund requires verified provider cost recovery policy")

    if leg == "refund" and (row.provider_cost != 0 or
            (row.quote_snapshot or {}).get("fee_payer") != "tenant"):
        raise TransactionError("Refund requires certified provider cost and payer policy")

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


def plan_next_operation(db: Session, *, merchant_id: str, application_id: str,
                        transaction_id: str) -> dict:
    """Read-only worker planning. Never reserve, dispatch, post or retry money."""
    from database.models import Application
    from database.models.mpesa_pass_through_identity import MpesaPassThroughLegIdentity
    from services.mpesa_pass_through_store import load_lifecycle
    from services.mpesa_pass_through_lifecycle import LegStatus
    row = find_owned(db, merchant_id=merchant_id, application_id=application_id,
                     record_id=transaction_id)
    app = db.get(Application, application_id)
    if row is None or app is None or app.merchant_id != merchant_id or app.environment not in {"test", "live"}:
        raise TransactionError("Transaction not found in authorized environment")
    def decision(action, leg=None, reference=None):
        return {"action": action, "leg": leg, "reference": reference,
                "environment": app.environment, "dispatch_authorized": False}
    if (row.quote_snapshot or {}).get("reversal_holds"):
        return decision("reversal_investigation")
    tx = load_lifecycle(row)
    for name in ("funding", "onward", "refund"):
        movement = getattr(tx, name)
        if movement.status in {LegStatus.PROCESSING, LegStatus.UNKNOWN}:
            intent = db.scalar(select(MpesaPassThroughOperationIntent).where(
                MpesaPassThroughOperationIntent.transaction_id == row.id,
                MpesaPassThroughOperationIntent.merchant_id == merchant_id,
                MpesaPassThroughOperationIntent.application_id == application_id,
                MpesaPassThroughOperationIntent.leg == name,
                MpesaPassThroughOperationIntent.reference == movement.reference))
            if intent is None:
                return decision("investigate_missing_reservation", name)
            binding = db.scalar(select(MpesaPassThroughLegIdentity).where(
                MpesaPassThroughLegIdentity.intent_id == intent.id))
            if binding is None:
                return decision("investigate_missing_binding", name, intent.reference)
            if intent.state == "closed":
                return decision("investigate_conflicting_state", name, intent.reference)
            return decision("query_existing_reference", name, intent.reference)
    if tx.refund.status == LegStatus.SUCCEEDED:
        return decision("refunded")
    if tx.onward.status == LegStatus.SUCCEEDED:
        return decision("completed" if tx.funding.status == LegStatus.SUCCEEDED else "investigate_conflicting_state")
    if tx.refund.status == LegStatus.FAILED:
        return decision("manual_refund_review")
    if tx.funding.status == LegStatus.FAILED:
        return decision("funding_failed")
    if tx.funding.status == LegStatus.NOT_STARTED:
        return decision("await_funding_authorization", "funding")
    if tx.funding.status == LegStatus.SUCCEEDED:
        saved = (row.quote_snapshot or {}).get("verified_provider_costs", {}).get("funding")
        if not saved or saved.get("provider_id") != tx.funding.provider_transaction_id or saved.get("movement_digest") != tx.funding.evidence_hash or not saved.get("cost_digest"):
            return decision("await_verified_funding_cost", "funding")
        if tx.onward.status == LegStatus.FAILED:
            return decision("manual_refund_review")
        return decision("await_onward_authorization", "onward")
    return decision("manual_review")
