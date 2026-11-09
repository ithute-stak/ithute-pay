"""Internal one-time binding for operation source and destination identities.

The caller must derive parties from approved shortcode ownership, merchant
contracts and the immutable payout beneficiary. No public API is exposed.
Binding cannot be changed after the operation has been reserved or observed.
A replay with identical parties is safe; a different party is rejected.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models.mpesa_pass_through_identity import MpesaPassThroughLegIdentity
from database.models.mpesa_pass_through_outbox import MpesaPassThroughOperationIntent
from services.mpesa_pass_through_lifecycle import TransactionError
from services.mpesa_pass_through_store import find_owned


def bind_leg_identity(
    db: Session, *, merchant_id: str, application_id: str, transaction_id: str,
    leg: str, source_party: str, destination_party: str,
) -> MpesaPassThroughLegIdentity:
    """Use only with server-side verified sender and beneficiary account data.

    No HTTP field should directly control source_party or destination_party.
    Caller commits binding transaction before any provider dispatch/query.
    """
    if leg not in {"funding", "onward", "refund"}:
        raise TransactionError("Invalid operation leg")
    if not source_party or not destination_party or (
        any(len(p) > 64 or p != p.strip() for p in (source_party, destination_party))
    ):
        raise TransactionError("Invalid reserved account identity")
    row = find_owned(db, merchant_id=merchant_id, application_id=application_id,
                     record_id=transaction_id, for_update=True)
    if row is None:
        raise TransactionError("Transaction outside authorized tenant scope")
    intent = db.scalar(select(MpesaPassThroughOperationIntent).where(
        MpesaPassThroughOperationIntent.transaction_id == transaction_id,
        MpesaPassThroughOperationIntent.merchant_id == merchant_id,
        MpesaPassThroughOperationIntent.application_id == application_id,
        MpesaPassThroughOperationIntent.leg == leg,
    ).with_for_update())
    if intent is None or intent.provider != "mpesa":
        raise TransactionError("Reserved M-Pesa intent not found")
    if intent.state != "reserved":
        raise TransactionError("Cannot bind an operation after reconciliation")
    previous = db.scalar(select(MpesaPassThroughLegIdentity).where(
        MpesaPassThroughLegIdentity.intent_id == intent.id,
    ))
    if previous:
        if previous.source_party != source_party or previous.destination_party != destination_party:
            raise TransactionError("Attempt to change immutable operation beneficiary or sender")
        return previous
    binding = MpesaPassThroughLegIdentity(
        intent_id=intent.id, source_party=source_party,
        destination_party=destination_party,
    )
    db.add(binding)
    db.flush()
    return binding
