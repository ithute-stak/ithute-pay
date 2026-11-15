from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from database.models import Payout, ProviderOperation
from integrations.mpesa.contracts import require_provider_capability
from services.events import publish_event
from services.funding import credit_direct_funding, funding_account
from services.direct_funding_amounts import verified_direct_funding_amount
from services.direct_funding_provider_identity import require_matching_provider_transaction
from services.funding_accounting import book_direct_company_funding
from services.loanhub_funding import build_direct_funding_provider, direct_funding_configuration
from services.payments import execute_payout
from services.provider_operations import apply_operation_result
from utils.helpers import conversation_id


def _publish_payout_failure(db: Session, payout: Payout, operation: ProviderOperation) -> None:
    metadata = dict(payout.metadata_json or {})
    publish_event(
        db,
        application_id=payout.application_id,
        merchant_id=payout.merchant_id,
        event_type="payout.failed",
        data={
            "id": payout.public_id,
            "status": "failed",
            "amount": payout.amount,
            "currency": payout.currency,
            "reference": payout.reference,
            "provider": payout.provider,
            "metadata": metadata,
            "failure_code": operation.response_code,
            "failure_message": operation.response_description,
            "funding_phase": "direct_mpesa",
        },
    )


async def reconcile_direct_funding_payout(db: Session, payout: Payout, operation: ProviderOperation) -> Payout:
    """Resolve a JIT lender funding transfer then continue the exact same payout.

    Provider callbacks may update the operation before this worker runs. Unknown
    or processing results are queried, never re-issued, so the lender cannot be
    debited twice after a timeout.
    """
    # Do not accept an arbitrary operation supplied by another tenant or
    # unrelated payout. Confirm exact ownership before querying the provider,
    # updating ledgers, or allowing any payout handoff.
    metadata = payout.metadata_json if isinstance(payout.metadata_json, dict) else {}
    if (metadata.get("funding_mode") != "direct_mpesa"
            or str(metadata.get("direct_funding_operation_id") or "") != operation.id
            or operation.resource_type != "payout"
            or operation.resource_id != payout.id
            or operation.operation_type != "payout.direct_funding"
            or operation.merchant_id != payout.merchant_id
            or operation.application_id != payout.application_id
            or operation.provider != payout.provider):
        raise ValueError("Direct funding operation does not match payout scope")
    # Funding review is not permitted to overwrite a customer payout that
    # has already been dispatched or resolved. Such a payout has a separate
    # provider transaction and its own read-only reconciliation path.
    if payout.status in {"processing", "unknown", "succeeded", "failed"}:
        return payout
    if operation.status in {"processing", "unknown"}:
        config = direct_funding_configuration(db, payout)
        provider = build_direct_funding_provider(config)
        require_provider_capability(provider, "query")
        query_reference = operation.provider_transaction_id or operation.conversation_id or operation.third_party_conversation_id
        if not query_reference:
            return payout
        result = await provider.query(query_reference=query_reference, third_party_conversation_id=conversation_id())
        require_matching_provider_transaction(operation, result)
        apply_operation_result(db, operation, result)
        db.commit(); db.refresh(operation)

    if operation.status == "failed":
        payout.status = "failed"
        payout.failure_code = operation.response_code
        payout.failure_message = operation.response_description
        db.add(payout)
        _publish_payout_failure(db, payout, operation)
        db.commit(); db.refresh(payout)
        return payout
    if operation.status != "succeeded":
        return payout

    metadata = dict(payout.metadata_json or {})
    required = verified_direct_funding_amount(payout)
    reference = str(metadata.get("funding_account_reference") or "").strip()
    account = funding_account(
        db, merchant_id=payout.merchant_id, application_id=payout.application_id,
        account_reference=reference, currency=payout.currency, for_update=True,
    )
    if not account or required <= 0:
        return payout

    credit_direct_funding(
        db, account=account, payout_id=payout.id,
        provider_operation_id=operation.id, amount=required,
    )
    book_direct_company_funding(db, operation, amount=required, currency=payout.currency)
    metadata["direct_funding_completed"] = True
    payout.metadata_json = metadata
    db.add(payout); db.commit(); db.refresh(payout)
    return await execute_payout(db, payout)
