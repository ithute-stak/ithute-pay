from __future__ import annotations
from sqlalchemy.orm import Session
from integrations.base import ProviderResult
from database.models import ProviderOperation
from utils.helpers import conversation_id


def create_operation(db: Session, *, merchant_id: str, application_id: str, provider: str,
                     operation_type: str, resource_type: str, resource_id: str) -> ProviderOperation:
    row = ProviderOperation(
        merchant_id=merchant_id,
        application_id=application_id,
        provider=provider,
        operation_type=operation_type,
        resource_type=resource_type,
        resource_id=resource_id,
        third_party_conversation_id=conversation_id(),
    )
    db.add(row)
    db.flush()
    return row


def apply_operation_result(db: Session, operation: ProviderOperation, result: ProviderResult) -> ProviderOperation:
    operation.status = result.status
    operation.conversation_id = result.conversation_id or operation.conversation_id
    operation.provider_transaction_id = result.transaction_id or operation.provider_transaction_id
    operation.response_code = result.response_code
    operation.response_description = result.response_description
    operation.raw_response = result.raw
    db.add(operation)
    return operation
