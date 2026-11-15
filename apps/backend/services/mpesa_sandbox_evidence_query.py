"""Tenant-scoped M-Pesa sandbox evidence query without financial side effects.

This is an explicitly read-only diagnostic helper. A privileged caller must
supply its selected/approved M-Pesa provider adapter. No live environment,
payment dispatch, callbacks, settlement, journal posting or state transition
is allowed. A successful sandbox response is NOT settlement attestation.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import ProviderTransaction
from integrations.base import ProviderResult
from integrations.mpesa.contracts import require_provider_capability
from services.transaction_evidence_assessment import assess_transaction_evidence
from utils.helpers import conversation_id


async def query_mpesa_sandbox_transaction_evidence(
    db: Session, *, merchant_id: str, application_id: str,
    transaction_id: str, provider: object,
) -> dict:
    """Query an existing tenant transaction exactly once, without posting it."""
    transaction = db.scalar(
        select(ProviderTransaction).where(
            ProviderTransaction.id == transaction_id,
            ProviderTransaction.merchant_id == merchant_id,
            ProviderTransaction.application_id == application_id,
            ProviderTransaction.provider == "mpesa",
            ProviderTransaction.resource_type.in_(("payment_intent", "payout")),
        )
    )
    if transaction is None:
        raise ValueError("M-Pesa transaction unavailable in requested scope")
    if str(getattr(provider, "environment", "")).lower() != "sandbox":
        raise ValueError("Read-only evidence query requires a sandbox M-Pesa adapter")
    require_provider_capability(provider, "query")
    reference = (
        transaction.provider_transaction_id
        or transaction.conversation_id
        or transaction.third_party_conversation_id
    )
    if not reference:
        raise ValueError("Existing transaction has no provider query reference")
    result = await provider.query(
        query_reference=reference, third_party_conversation_id=conversation_id()
    )
    if not isinstance(result, ProviderResult):
        raise ValueError("Provider query did not produce a normalized response")
    assessment = assess_transaction_evidence(transaction=transaction, result=result)
    assessment["provider_queried"] = True
    assessment["query_environment"] = "sandbox"
    assessment["query_reference_type"] = (
        "transaction_id" if transaction.provider_transaction_id
        else "conversation_id" if transaction.conversation_id
        else "third_party_conversation_id"
    )
    # A read-only query itself does not independently attest settlement or
    # authorize financial posting, even if the provider reports success.
    return assessment
