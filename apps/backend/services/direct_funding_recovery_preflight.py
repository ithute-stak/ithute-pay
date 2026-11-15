"""Read-only evidence assessment for an existing direct-funding payout.

Never queries a payment provider, changes a payout or dispatches funds.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import Payout, ProviderOperation


def assess_direct_funding(db: Session, *, merchant_id: str, application_id: str, payout_id: str) -> dict:
    payout = db.scalar(select(Payout).where(
        Payout.id == payout_id, Payout.merchant_id == merchant_id,
        Payout.application_id == application_id,
    ))
    if payout is None:
        raise ValueError("Payout unavailable in requested scope")
    metadata = payout.metadata_json if isinstance(payout.metadata_json, dict) else {}
    if metadata.get("funding_mode") != "direct_mpesa":
        raise ValueError("Not a direct-funding payout")
    funding_id = str(metadata.get("direct_funding_operation_id") or "")
    operations = db.scalars(select(ProviderOperation).where(
        ProviderOperation.merchant_id == merchant_id,
        ProviderOperation.application_id == application_id,
        ProviderOperation.resource_type == "payout",
        ProviderOperation.resource_id == payout_id,
        ProviderOperation.operation_type == "payout.direct_funding",
    )).all()
    operation = operations[0] if len(operations) == 1 and operations[0].id == funding_id else None
    reference = (operation.provider_transaction_id or operation.conversation_id
                 or operation.third_party_conversation_id) if operation else None

    if not operation:
        action, reason = "manual_review", "missing_or_ambiguous_operation"
    elif operation.status in {"processing", "unknown"} and reference:
        action, reason = "read_only_provider_query", "unresolved_provider_result"
    elif operation.status == "succeeded":
        action, reason = "verify_posting_and_payout", "funding_recorded_success"
    else:
        action, reason = "manual_review", "unverified_funding"

    return {
        "payout_id": payout.id, "merchant_id": merchant_id, "application_id": application_id,
        "payout_status": payout.status,
        "funding_status": operation.status if operation else "missing",
        "funding_operation_id": operation.id if operation else None,
        "query_reference": reference if action == "read_only_provider_query" else None,
        "recommended_action": action, "reason": reason,
        "read_only": True, "provider_queried": False, "payment_dispatched": False,
        "automatic_finalization_enabled": False,
    }
