from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from database.models import IdempotencyRecord


def get_existing(db: Session, *, application_id: str, key: str, operation: str,
                 request_hash: str) -> IdempotencyRecord | None:
    row = db.scalar(select(IdempotencyRecord).where(
        IdempotencyRecord.application_id == application_id,
        IdempotencyRecord.key == key,
        IdempotencyRecord.operation == operation,
    ))
    if row and row.request_hash != request_hash:
        raise HTTPException(status_code=409, detail="Idempotency-Key was already used with a different request")
    return row


def save_record(db: Session, *, application_id: str, key: str, operation: str,
                request_hash: str, resource_type: str, resource_id: str,
                response_json: dict) -> IdempotencyRecord:
    row = IdempotencyRecord(
        application_id=application_id,
        key=key,
        operation=operation,
        request_hash=request_hash,
        resource_type=resource_type,
        resource_id=resource_id,
        response_json=response_json,
    )
    db.add(row)
    db.flush()
    return row
