from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from database.models import Payout, ProviderOperation
from integrations.mpesa.contracts import require_provider_capability
from services.events import publish_event
from services.funding import credit_direct_funding, funding_account
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
    if operation.status in {"processing", "unknown"}:
        config = direct_funding_configuration(db, payout)
        provider = build_direct_funding_provider(config)
        require_provider_capability(provider, "query")
        query_reference = operation.provider_transaction_id or operation.conversation_id or operation.third_party_conversation_id
        if not query_reference:
            return payout
        result = await provider.query(query_reference=query_reference, third_party_conversation_id=conversation_id())
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
    required = Decimal(str(metadata.get("funding_debit_amount") or 0))
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
