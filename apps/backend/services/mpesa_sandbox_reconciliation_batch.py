"""Bounded, read-only M-PESA sandbox reconciliation review.

This helper never posts accounts or changes payment states. It is an internal
service building block, NOT a public API or production activation. The caller
must supply an already-authorized sandbox provider and tenant scope.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import ProviderTransaction
from integrations.mpesa.contracts import require_provider_capability
from services.mpesa_sandbox_evidence_query import query_mpesa_sandbox_transaction_evidence

MAX_SANDBOX_REVIEW_BATCH = 10


async def assess_mpesa_sandbox_batch(
    db: Session, *, merchant_id: str, application_id: str,
    transaction_ids: list[str], provider: object,
) -> dict:
    """Prevalidate the entire scoped batch before any provider network lookup.

    Individual provider failures are sanitized and isolated. A failed lookup
    must not hide the outcome of the other transactions. Even a complete
    report does not constitute provider attestation or authorize settlement.
    """
    if (not isinstance(transaction_ids, list)
            or not 1 <= len(transaction_ids) <= MAX_SANDBOX_REVIEW_BATCH
            or any(not isinstance(item, str) or not item.strip() for item in transaction_ids)
            or len(set(transaction_ids)) != len(transaction_ids)):
        raise ValueError("Review requires 1-10 distinct transaction IDs")
    if str(getattr(provider, "environment", "")).strip().lower() != "sandbox":
        raise ValueError("M-PESA reconciliation batch requires sandbox provider")
    require_provider_capability(provider, "query")

    scoped = db.scalars(
        select(ProviderTransaction).where(
            ProviderTransaction.id.in_(transaction_ids),
            ProviderTransaction.merchant_id == merchant_id,
            ProviderTransaction.application_id == application_id,
            ProviderTransaction.provider == "mpesa",
            ProviderTransaction.resource_type.in_(("payment_intent", "payout")),
        )
    ).all()
    by_id = {record.id: record for record in scoped}
    if len(by_id) != len(transaction_ids):
        raise ValueError("One or more transactions unavailable in requested scope")
    # A broken reference aborts preflight for the ENTIRE batch. Do not make a
    # partial set of network requests before discovering an invalid instruction.
    if any(
        not (by_id[item].provider_transaction_id
             or by_id[item].conversation_id
             or by_id[item].third_party_conversation_id)
        for item in transaction_ids
    ):
        raise ValueError("One or more transactions have no provider query reference")

    items = []
    for transaction_id in transaction_ids:
        try:
            report = await query_mpesa_sandbox_transaction_evidence(
                db, merchant_id=merchant_id, application_id=application_id,
                transaction_id=transaction_id, provider=provider,
            )
        except Exception:
            # Do not expose provider exceptions: these may contain credentials,
            # raw upstream payloads or customer data. This is review-only.
            items.append({
                "transaction_id": transaction_id,
                "outcome": "query_error",
                "review_findings": ["provider_lookup_failed_manual_review"],
                "financial_action_authorized": False,
            })
        else:
            items.append({
                "transaction_id": transaction_id,
                "outcome": "review_required",
                "review_findings": report["review_findings"],
                "evidence": report,
                "financial_action_authorized": False,
            })
    return {
        "merchant_id": merchant_id,
        "application_id": application_id,
        "count": len(items),
        "query_error_count": sum(item["outcome"] == "query_error" for item in items),
        "items": items,
        "environment": "sandbox",
        "read_only": True,
        "independent_settlement_verified": False,
        "automatic_finalization_enabled": False,
        "financial_action_authorized": False,
    }
