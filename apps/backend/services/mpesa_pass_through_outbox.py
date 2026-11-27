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

    from database.models import Application
    app = db.get(Application, application_id)
    if app is None or app.merchant_id != merchant_id or app.environment not in {"test", "live"}:
        raise TransactionError("Invalid reservation application scope")
    if app.environment == "live" and leg in {"onward", "refund"}:
        # A successful status alone must not authorize a new live movement.
        # Reuse the accounting receipt/amount validation, without posting.
        from services.mpesa_pass_through_accounting import _require_confirmed_leg
        _require_confirmed_leg(db, row, "funding")

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
    if app.environment == "live":
        from services.mpesa_pass_through_accounting import _require_confirmed_leg
        for name in ("funding", "onward", "refund"):
            if getattr(tx, name).status == LegStatus.SUCCEEDED:
                try:
                    _require_confirmed_leg(db, row, name)
                except TransactionError:
                    return decision("investigate_unverified_live_settlement", name)
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


async def run_sandbox_reconciliation_check(db: Session, *, merchant_id: str,
                                           application_id: str, transaction_id: str,
                                           client, conversation_reference: str) -> dict:
    """One explicit diagnostic query, never a dispatch or accounting worker.

    Client must be constructed by trusted code with approved sandbox credentials.
    No automatic retries, scheduling, settlement confirmation or journal writes.
    Caller should use a short-lived read-only session.
    """
    from database.models.mpesa_pass_through_identity import MpesaPassThroughLegIdentity
    from services.mpesa_pass_through_evidence import ExpectedMovement
    from services.mpesa_pass_through_query_probe import probe_sandbox_query
    plan = plan_next_operation(db, merchant_id=merchant_id,
        application_id=application_id, transaction_id=transaction_id)
    if plan["environment"] != "test" or getattr(client, "environment", None) != "sandbox":
        raise TransactionError("Reconciliation diagnostic requires test application and sandbox client")
    if plan["action"] != "query_existing_reference":
        return {**plan, "query_performed": False, "accounting_authorized": False}
    intent = db.scalar(select(MpesaPassThroughOperationIntent).where(
        MpesaPassThroughOperationIntent.transaction_id == transaction_id,
        MpesaPassThroughOperationIntent.merchant_id == merchant_id,
        MpesaPassThroughOperationIntent.application_id == application_id,
        MpesaPassThroughOperationIntent.leg == plan["leg"],
        MpesaPassThroughOperationIntent.reference == plan["reference"],
    ))
    if intent is None or intent.provider != "mpesa" or intent.state not in {"reserved", "needs_reconciliation"}:
        raise TransactionError("Existing unresolved M-Pesa reservation required")
    binding = db.scalar(select(MpesaPassThroughLegIdentity).where(
        MpesaPassThroughLegIdentity.intent_id == intent.id))
    if binding is None:
        raise TransactionError("Immutable provider party binding required")
    expected = ExpectedMovement(intent.reference, intent.amount, intent.currency,
                                binding.source_party, binding.destination_party)
    result = await probe_sandbox_query(client, expected=expected,
        third_party_conversation_id=conversation_reference)
    return {**plan, "query_performed": True, "observed_status": result.status,
            "identity_evidence_sufficient": result.sufficient_evidence,
            "missing_fields": result.missing_fields,
            "accounting_authorized": False}


def claim_sandbox_simulation(db: Session, *, merchant_id: str, application_id: str,
                             transaction_id: str, leg: str, reference: str) -> bool:
    """One-way claim for a sandbox simulation; never grants dispatch permission.

    Commit before starting any simulation. A committed claim survives a crash
    and must be reconciled, not reset or treated as permission to send money.
    No provider calls, submitted timestamps or accounting changes occur here.
    """
    from database.models import Application
    from database.models.mpesa_pass_through_identity import MpesaPassThroughLegIdentity
    from sqlalchemy import update
    row = find_owned(db, merchant_id=merchant_id, application_id=application_id,
                     record_id=transaction_id, for_update=True)
    app = db.get(Application, application_id)
    if row is None or app is None or app.merchant_id != merchant_id or app.environment != "test":
        raise TransactionError("Simulation claim requires authorized test application")
    if (row.quote_snapshot or {}).get("reversal_holds"):
        raise TransactionError("Transaction held for reversal investigation")
    if leg not in {"funding", "onward", "refund"}:
        raise TransactionError("Unknown movement")
    if getattr(row, leg + "_status") != "processing" or getattr(row, leg + "_reference") != reference:
        raise TransactionError("Matching processing movement required")
    intent = db.scalar(select(MpesaPassThroughOperationIntent).where(
        MpesaPassThroughOperationIntent.transaction_id == row.id,
        MpesaPassThroughOperationIntent.merchant_id == merchant_id,
        MpesaPassThroughOperationIntent.application_id == application_id,
        MpesaPassThroughOperationIntent.leg == leg,
        MpesaPassThroughOperationIntent.reference == reference,
        MpesaPassThroughOperationIntent.provider == "mpesa",
    ).with_for_update())
    if intent is None:
        raise TransactionError("Matching reservation required")
    binding = db.scalar(select(MpesaPassThroughLegIdentity).where(
        MpesaPassThroughLegIdentity.intent_id == intent.id))
    if binding is None:
        raise TransactionError("Immutable party binding required")
    if leg != "funding":
        saved = (row.quote_snapshot or {}).get("verified_provider_costs", {}).get("funding")
        if (row.funding_status != "succeeded" or not saved or
                saved.get("provider_id") != row.funding_provider_id or
                saved.get("movement_digest") != row.funding_evidence_hash or not saved.get("cost_digest")):
            raise TransactionError("Verified funding cost evidence required")
    result = db.execute(update(MpesaPassThroughOperationIntent).where(
        MpesaPassThroughOperationIntent.id == intent.id,
        MpesaPassThroughOperationIntent.state == "reserved",
        MpesaPassThroughOperationIntent.submitted_at.is_(None),
        MpesaPassThroughOperationIntent.provider_operation_id.is_(None),
    ).values(state="needs_reconciliation"))
    db.flush()
    return result.rowcount == 1
