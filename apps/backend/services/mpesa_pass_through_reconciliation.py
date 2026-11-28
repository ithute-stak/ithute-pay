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

from decimal import Decimal
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session
from database.models import Application

from database.models.mpesa_pass_through_identity import (
    MpesaPassThroughLegIdentity, MpesaPassThroughProviderReceipt,
)
from services.mpesa_pass_through_evidence import evidence_digest
from database.models.mpesa_pass_through_outbox import MpesaPassThroughOperationIntent
from services.mpesa_pass_through_accounting import post_verified_outgoing, post_verified_incoming, preview_incoming_allocation
from services.mpesa_pass_through_evidence import (
    ExpectedMovement, ProviderQueryObservation, validate_provider_query,
    ProviderCostObservation, validate_provider_cost,
)
from services.mpesa_pass_through_lifecycle import TransactionError
from services.mpesa_pass_through_store import find_owned, record_verified_evidence, load_lifecycle


def reconcile_authenticated_query(
    db: Session, *, merchant_id: str, application_id: str,
    transaction_id: str, leg: str,
    source_shortcode: str, destination: str,
    observation: ProviderQueryObservation,
    cost_observation: ProviderCostObservation | None = None,
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
    if (row.quote_snapshot or {}).get("reversal_holds"):
        raise TransactionError("Transaction held for provider reversal investigation")
    app = db.get(Application, application_id)
    if app is None or app.merchant_id != merchant_id or app.environment not in {"test", "live"}:
        raise TransactionError("Invalid application environment or ownership")
    live = app.environment == "live"
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
    binding = db.scalar(select(MpesaPassThroughLegIdentity).where(
        MpesaPassThroughLegIdentity.intent_id == intent.id,
    ))
    if binding is None:
        raise TransactionError("Missing immutable provider party binding")
    if (source_shortcode != binding.source_party or
            destination != binding.destination_party):
        raise TransactionError("Reconciliation parties differ from committed binding")
    expected = ExpectedMovement(
        reference=intent.reference, amount=intent.amount, currency=intent.currency,
        source_shortcode=binding.source_party, destination=binding.destination_party,
    )
    attested = validate_provider_query(expected, observation)
    incoming = row.direction == "incoming"
    if incoming and leg == "refund":
        raise TransactionError("Incoming refund reconciliation not yet certified")
    snapshot = dict(row.quote_snapshot or {})
    costs = dict(snapshot.get("verified_provider_costs") or {})
    if live and attested.outcome == "succeeded" and cost_observation is None:
        raise TransactionError("Live settlement requires actual provider cost and credit evidence")
    if live and attested.outcome == "succeeded" and cost_observation.source_debit is None:
        raise TransactionError("Live settlement requires actual source debit evidence")
    # Check previous successful legs before any new mutation. A legacy gross-only
    # confirmation cannot authorize subsequent live settlement or revenue.
    if live:
        for prior in ("funding", "onward", "refund"):
            if prior == leg or getattr(row, prior + "_status") != "succeeded":
                continue
            saved = costs.get(prior)
            if (not saved or saved.get("provider_id") != getattr(row, prior + "_provider_id")
                    or saved.get("movement_digest") != getattr(row, prior + "_evidence_hash")
                    or not saved.get("cost_digest") or saved.get("source_debit") is None):
                raise TransactionError("Prior live movement lacks matched settlement evidence")
    if incoming and attested.outcome == "succeeded":
        if cost_observation is None:
            raise TransactionError("Actual provider cost evidence required")
        verified = validate_provider_cost(expected, attested, cost_observation)
        if leg == "funding":
            preview_incoming_allocation(load_lifecycle(row).quote,
                actual_provider_cost=verified.deducted_fee, actual_master_credit=verified.net_credit)
        elif verified.deducted_fee != 0 or verified.net_credit != row.onward_amount:
            raise TransactionError("Unexpected onward provider deduction or recipient credit")
        record = {"provider_id": attested.transaction_id,
                  "movement_digest": evidence_digest(attested),
                  "cost_digest": sha256(verified.canonical_evidence).hexdigest(),
                  "fee": format(verified.deducted_fee, ".2f"), "net": format(verified.net_credit, ".2f"),
                  **({"source_debit": format(verified.source_debit, ".2f")} if verified.source_debit is not None else {})}
        if leg in costs and costs[leg] != record:
            raise TransactionError("Conflicting provider cost evidence")
        costs[leg] = record
        snapshot["verified_provider_costs"] = costs
    elif not incoming and attested.outcome == "succeeded" and cost_observation is not None:
        verified = validate_provider_cost(expected, attested, cost_observation)
        if verified.deducted_fee != 0 or verified.net_credit != intent.amount:
            raise TransactionError("Outgoing provider deduction or recipient credit differs from certified zero-cost policy")
        record = {"provider_id": attested.transaction_id,
                  "movement_digest": evidence_digest(attested),
                  "cost_digest": sha256(verified.canonical_evidence).hexdigest(),
                  "fee": format(verified.deducted_fee, ".2f"), "net": format(verified.net_credit, ".2f"),
                  **({"source_debit": format(verified.source_debit, ".2f")} if verified.source_debit is not None else {})}
        if leg in costs and costs[leg] != record:
            raise TransactionError("Conflicting provider cost evidence")
        costs[leg] = record
        snapshot["verified_provider_costs"] = costs
    elif cost_observation is not None:
        raise TransactionError("Unexpected cost evidence for movement")
    # Existing offline fixtures without settlement observations remain supported.
    # The future live dispatcher must require actual cost/credit for every leg.
    if not incoming and leg in costs and cost_observation is None and attested.outcome == "succeeded":
        raise TransactionError("Previously attested provider cost evidence required on replay")
    if attested.outcome == "succeeded":
        if not attested.transaction_id:
            raise TransactionError("Successful movement lacks provider ID")
        existing_receipt = db.scalar(select(MpesaPassThroughProviderReceipt).where(
            MpesaPassThroughProviderReceipt.intent_id == intent.id,
        ))
        digest = evidence_digest(attested)
        if existing_receipt:
            if (existing_receipt.provider != "mpesa" or
                    existing_receipt.provider_transaction_id != attested.transaction_id or
                    existing_receipt.canonical_evidence_hash != digest):
                raise TransactionError("Conflicting receipt for reserved movement")
        else:
            # The unique (provider, transaction_id) constraint is authoritative
            # even for concurrent workers. On IntegrityError the entire caller
            # transaction must be rolled back and investigated, never replayed.
            receipt = MpesaPassThroughProviderReceipt(
                intent_id=intent.id, provider="mpesa",
                provider_transaction_id=attested.transaction_id,
                canonical_evidence_hash=digest,
            )
            db.add(receipt)
            db.flush()
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
        row.quote_snapshot = snapshot
        post_verified_outgoing(
            db, merchant_id=merchant_id, application_id=application_id,
            transaction_id=row.id,
        )
    else:
        row.quote_snapshot = snapshot
        if row.funding_status == "succeeded":
            funding = costs.get("funding")
            if not funding or funding["provider_id"] != row.funding_provider_id or funding["movement_digest"] != row.funding_evidence_hash:
                raise TransactionError("Missing matched funding cost evidence")
            onward = costs.get("onward")
            if row.onward_status == "succeeded" and (not onward or onward["provider_id"] != row.onward_provider_id
                    or onward["movement_digest"] != row.onward_evidence_hash):
                raise TransactionError("Missing matched onward cost evidence")
            post_verified_incoming(db, merchant_id=merchant_id, application_id=application_id,
                transaction_id=row.id, actual_provider_cost=Decimal(funding["fee"]),
                actual_master_credit=Decimal(funding["net"]),
                actual_recipient_credit=Decimal(onward["net"]) if onward else None)
    db.flush()
    return attested.outcome


def quarantine_authenticated_reversal(
    db: Session, *, merchant_id: str, application_id: str,
    transaction_id: str, leg: str, observation: ProviderQueryObservation,
) -> dict:
    """Persist a reversal hold without undoing journals or authorizing funds.

    Trusted provider query caller only. The original successful movement must
    match the immutable reservation and receipt. A reversal notice alone
    does not prove the amount recovered or the party bearing the loss.
    """
    from dataclasses import replace
    if leg not in {"funding", "onward", "refund"} or observation.reversed is not True:
        raise TransactionError("Explicit provider reversal required")
    row = find_owned(db, merchant_id=merchant_id, application_id=application_id,
                     record_id=transaction_id, for_update=True)
    if row is None or getattr(row, leg + "_status") != "succeeded":
        raise TransactionError("Original confirmed movement required")
    intent = db.scalar(select(MpesaPassThroughOperationIntent).where(
        MpesaPassThroughOperationIntent.transaction_id == row.id,
        MpesaPassThroughOperationIntent.merchant_id == merchant_id,
        MpesaPassThroughOperationIntent.application_id == application_id,
        MpesaPassThroughOperationIntent.leg == leg,
    ).with_for_update())
    if intent is None:
        raise TransactionError("Original reserved operation required")
    binding = db.scalar(select(MpesaPassThroughLegIdentity).where(
        MpesaPassThroughLegIdentity.intent_id == intent.id))
    receipt = db.scalar(select(MpesaPassThroughProviderReceipt).where(
        MpesaPassThroughProviderReceipt.intent_id == intent.id))
    if binding is None or receipt is None or receipt.provider != "mpesa":
        raise TransactionError("Original provider receipt and party binding required")
    expected = ExpectedMovement(intent.reference, intent.amount, intent.currency,
                                binding.source_party, binding.destination_party)
    # Validate the original movement identity, not the financial outcome of
    # the reversal. No change to the original confirmed state is permitted.
    original = validate_provider_query(expected, replace(observation, reversed=False,
                                                          status="succeeded"))
    digest = evidence_digest(original)
    if (original.transaction_id != receipt.provider_transaction_id or
            original.transaction_id != getattr(row, leg + "_provider_id") or
            digest != receipt.canonical_evidence_hash or
            digest != getattr(row, leg + "_evidence_hash")):
        raise TransactionError("Reversal does not match original confirmed receipt")
    snapshot = dict(row.quote_snapshot or {})
    holds = dict(snapshot.get("reversal_holds") or {})
    hold = {"leg": leg, "provider_id": original.transaction_id,
            "original_evidence_digest": digest,
            "reversal_evidence_digest": sha256(original.canonical_evidence + b":reversed").hexdigest(),
            "status": "investigation_required"}
    if leg in holds and holds[leg] != hold:
        raise TransactionError("Conflicting reversal hold")
    if leg not in holds:
        holds[leg] = hold
        snapshot["reversal_holds"] = holds
        row.quote_snapshot = snapshot
        row.version += 1
        db.flush()
    return hold


def preview_claimed_sandbox_settlement(
    db: Session, *, merchant_id: str, application_id: str,
    transaction_id: str, leg: str, observation: ProviderQueryObservation,
    cost_observation: ProviderCostObservation,
) -> dict:
    """Non-posting validation of a claimed test movement and settlement fields.

    Structural consistency is not authentication. Never call the posting
    reconciler here, and never accept a synthetic execution result as evidence.
    """
    if leg not in {"funding", "onward"}:
        raise TransactionError("Unsupported sandbox settlement movement")
    row = find_owned(db, merchant_id=merchant_id, application_id=application_id,
                     record_id=transaction_id)
    app = db.get(Application, application_id)
    if row is None or app is None or app.merchant_id != merchant_id or app.environment != "test":
        raise TransactionError("Settlement preview requires authorized test application")
    if (row.quote_snapshot or {}).get("reversal_holds"):
        raise TransactionError("Transaction held for reversal investigation")
    intent = db.scalar(select(MpesaPassThroughOperationIntent).where(
        MpesaPassThroughOperationIntent.transaction_id == row.id,
        MpesaPassThroughOperationIntent.merchant_id == merchant_id,
        MpesaPassThroughOperationIntent.application_id == application_id,
        MpesaPassThroughOperationIntent.leg == leg))
    if (intent is None or intent.provider != "mpesa" or intent.state != "needs_reconciliation"
            or getattr(row, leg + "_status") not in {"processing", "unknown"}
            or getattr(row, leg + "_reference") != intent.reference
            or intent.currency != row.currency
            or intent.amount != (row.funding_amount if leg == "funding" else row.onward_amount)):
        raise TransactionError("Matching unresolved claimed operation required")
    binding = db.scalar(select(MpesaPassThroughLegIdentity).where(
        MpesaPassThroughLegIdentity.intent_id == intent.id))
    if binding is None:
        raise TransactionError("Immutable party binding required")
    if not isinstance(observation, ProviderQueryObservation) or not isinstance(cost_observation, ProviderCostObservation):
        raise TransactionError("Separate query and settlement observations required")
    expected = ExpectedMovement(intent.reference, intent.amount, intent.currency,
                                binding.source_party, binding.destination_party)
    movement = validate_provider_query(expected, observation)
    if cost_observation.source_debit is None:
        raise TransactionError("Actual source debit evidence required")
    cost = validate_provider_cost(expected, movement, cost_observation)
    if row.direction == "incoming" and leg == "funding":
        preview_incoming_allocation(load_lifecycle(row).quote,
            actual_provider_cost=cost.deducted_fee, actual_master_credit=cost.net_credit)
    elif cost.deducted_fee != 0 or cost.net_credit != intent.amount:
        raise TransactionError("Unexpected provider deduction or beneficiary credit")
    return {
        "reference": intent.reference, "environment": "test",
        "structurally_consistent": True,
        "gross_amount": format(cost.gross_amount, ".2f"),
        "deducted_fee": format(cost.deducted_fee, ".2f"),
        "net_credit": format(cost.net_credit, ".2f"),
        "source_debit": format(cost.source_debit, ".2f"),
        "provider_evidence_authenticated": False,
        "settlement_verified": False, "accounting_authorized": False,
        "dispatch_authorized": False, "retry_authorized": False,
    }


def preview_reversal_recovery(
    db: Session, *, merchant_id: str, application_id: str, transaction_id: str,
    leg: str, original_provider_id: str, reversal_provider_id: str,
    actual_recovered_amount: Decimal, actual_reversal_cost: Decimal,
    statement_reference: str,
) -> dict:
    """Assess recovery against a held original movement, never release or post.

    An independently authenticated statement and approved loss allocation are
    required before a compensating journal can be designed. A reversal of a
    funding leg after onward settlement can create a different liability from
    a reversal of an onward leg; do not infer that both cancel the transaction.
    """
    if leg not in {"funding", "onward", "refund"}:
        raise TransactionError("Unknown reversal movement")
    row = find_owned(db, merchant_id=merchant_id, application_id=application_id,
                     record_id=transaction_id)
    app = db.get(Application, application_id)
    if row is None or app is None or app.merchant_id != merchant_id or app.environment != "test":
        raise TransactionError("Reversal preview requires authorized test application")
    hold = (row.quote_snapshot or {}).get("reversal_holds", {}).get(leg)
    if (not hold or hold.get("status") != "investigation_required"
            or hold.get("provider_id") != original_provider_id
            or original_provider_id != getattr(row, leg + "_provider_id")
            or hold.get("original_evidence_digest") != getattr(row, leg + "_evidence_hash")):
        raise TransactionError("Matching original reversal hold required")
    if (not isinstance(reversal_provider_id, str) or not reversal_provider_id.strip()
            or len(reversal_provider_id) > 100 or reversal_provider_id == original_provider_id
            or not isinstance(statement_reference, str) or not statement_reference.strip()
            or len(statement_reference) > 200):
        raise TransactionError("Separate reversal and statement identifiers required")
    for value in (actual_recovered_amount, actual_reversal_cost):
        if (not isinstance(value, Decimal) or not value.is_finite() or value < 0
                or value.as_tuple().exponent < -2):
            raise TransactionError("Invalid reversal recovery amount")
    original = row.onward_amount if leg == "onward" else row.funding_amount
    if actual_recovered_amount > original:
        raise TransactionError("Recovery exceeds original movement")
    return {
        "leg": leg, "original_amount": format(original, ".2f"),
        "reported_recovery": format(actual_recovered_amount, ".2f"),
        "reported_reversal_cost": format(actual_reversal_cost, ".2f"),
        "gross_recovery_gap": format(original - actual_recovered_amount + actual_reversal_cost, ".2f"),
        "onward_previously_confirmed": row.onward_status == "succeeded",
        "hold_release_authorized": False, "accounting_authorized": False,
        "refund_execution_authorized": False, "provider_evidence_authenticated": False,
        "loss_allocation_required": True,
    }
