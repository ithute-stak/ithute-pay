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
                  "fee": format(verified.deducted_fee, ".2f"), "net": format(verified.net_credit, ".2f")}
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
                  "fee": format(verified.deducted_fee, ".2f"), "net": format(verified.net_credit, ".2f")}
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
