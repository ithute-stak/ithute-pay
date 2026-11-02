"""Atomic idempotent reservation for merchant payment provider operations.

This is an opt-in service; callers must commit the reservation BEFORE
dispatching money-moving requests. The existing M-PESA/Golink paths are not
automatically redirected through it.
"""
from __future__ import annotations

import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.models import IdempotencyRecord, ProviderOperation
from services.payment_lifecycle import PaymentState, transition_payment


def payment_request_fingerprint(data: dict) -> str:
    """Canonical SHA256; never include secrets in the supplied input."""
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def reserve_provider_operation(
    db: Session, *, application_id: str, merchant_id: str, provider: str,
    operation_type: str, idempotency_key: str, request_hash: str,
    resource_type: str, resource_id: str, third_party_conversation_id: str,
) -> tuple[ProviderOperation, bool]:
    """Return (operation, newly_created). Caller MUST commit before network I/O.

    Conflicting/repeated keys never create a second provider operation.
    A pending or unknown operation is returned for status inspection, not dispatch.
    """
    if not 1 <= len(idempotency_key) <= 200:
        raise HTTPException(status_code=422, detail="Invalid Idempotency-Key length")
    operation_scope = f"provider:{provider}:{operation_type}"
    existing = db.scalar(select(IdempotencyRecord).where(
        IdempotencyRecord.application_id == application_id,
        IdempotencyRecord.key == idempotency_key,
        IdempotencyRecord.operation == operation_scope,
    ))
    if existing is not None:
        if existing.request_hash != request_hash:
            raise HTTPException(status_code=409, detail="Idempotency-Key reused with different request")
        if existing.resource_type != "provider_operation" or not existing.resource_id:
            raise HTTPException(status_code=409, detail="Idempotency reservation has inconsistent resource")
        record = db.get(ProviderOperation, existing.resource_id)
        if record is None or record.application_id != application_id or record.merchant_id != merchant_id:
            raise HTTPException(status_code=409, detail="Idempotency reservation cannot be reconciled")
        return record, False

    record = ProviderOperation(
        merchant_id=merchant_id,
        application_id=application_id,
        provider=provider,
        operation_type=operation_type,
        resource_type=resource_type,
        resource_id=resource_id,
        status=PaymentState.CREATED.value,
        third_party_conversation_id=third_party_conversation_id,
        raw_request={},
        raw_response={},
    )
    db.add(record)
    db.flush()
    db.add(IdempotencyRecord(
        application_id=application_id,
        key=idempotency_key,
        operation=operation_scope,
        request_hash=request_hash,
        resource_type="provider_operation",
        resource_id=record.id,
        response_json={"operation_id": record.id, "status": record.status},
    ))
    try:
        db.flush()
    except IntegrityError:
        # UniqueConstraint(application_id, key, operation) handles concurrent
        # reservations; caller must start a fresh transaction and read the winner.
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Concurrent payment reservation detected; query the original operation before retrying",
        ) from None
    return record, True


def advance_provider_operation(
    db: Session, *, operation_id: str, target: PaymentState | str,
    reconciled: bool = False,
) -> ProviderOperation:
    """Lock operation row and validate transition. Caller commits."""
    row = db.scalar(
        select(ProviderOperation).where(ProviderOperation.id == operation_id).with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Provider operation not found")
    row.status = transition_payment(row.status, target, reconciled=reconciled).value
    db.flush()
    return row


def claim_provider_dispatch(db: Session, *, operation_id: str) -> bool:
    """Atomically claim a new operation for one outbound provider request.

    Returns False if already claimed, processing, succeeded, failed, or unknown.
    MUST commit this state change before making any network request.
    An uncommitted claim does not provide crash-safe deduplication.
    """
    result = db.execute(
        update(ProviderOperation)
        .where(
            ProviderOperation.id == operation_id,
            ProviderOperation.status == PaymentState.CREATED.value,
        )
        .values(status=PaymentState.DISPATCHED.value)
        .execution_options(synchronize_session="fetch")
    )
    return result.rowcount == 1
