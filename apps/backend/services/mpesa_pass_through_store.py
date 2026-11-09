"""Transactional storage adapter for non-posting M-Pesa pass-through operations.

Public callers must be authenticated by the existing Merchant/Application API
boundary. The store accepts a server-computed Quote, never client fee values.
It does not call M-Pesa or send SMS. Transaction is committed by the caller.
"""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.models.mpesa_pass_through import MpesaPassThroughTransaction
from services.mpesa_pass_through_lifecycle import (
    Leg, LegStatus, PassThrough, TransactionError, begin, observe,
)
from services.mpesa_pass_through_quotes import Quote


def _request_digest(request: dict) -> str:
    encoded = json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _snapshot(quote: Quote) -> dict:
    return quote.payload()


def _restore(row: MpesaPassThroughTransaction) -> PassThrough:
    snapshot = row.quote_snapshot or {}
    quote = Quote(
        tenant_id=row.merchant_id,
        agreement_version=row.agreement_version,
        direction=row.direction,
        principal=row.principal,
        provider_cost=row.provider_cost,
        ithutepay_fee=row.platform_fee,
        funding_amount=row.funding_amount,
        onward_amount=row.onward_amount,
        fee_payer=str(snapshot["fee_payer"]),
    )
    legs = {}
    for name in ("funding", "onward", "refund"):
        legs[name] = Leg(
            status=LegStatus(getattr(row, name + "_status")),
            reference=getattr(row, name + "_reference"),
            provider_transaction_id=getattr(row, name + "_provider_id"),
            evidence_hash=getattr(row, name + "_evidence_hash"),
        )
    return PassThrough(transaction_id=row.id, quote=quote, **legs)


def create_quote_record(
    db: Session, *, merchant_id: str, application_id: str, idempotency_key: str,
    request: dict, quote: Quote,
) -> MpesaPassThroughTransaction:
    if not merchant_id or not application_id or quote.tenant_id != merchant_id:
        raise TransactionError("Authenticated merchant does not match the quote")
    if not idempotency_key or len(idempotency_key) > 180:
        raise TransactionError("Invalid idempotency key")
    payload_hash = _request_digest(request)
    existing = db.scalar(select(MpesaPassThroughTransaction).where(
        MpesaPassThroughTransaction.application_id == application_id,
        MpesaPassThroughTransaction.idempotency_key == idempotency_key,
    ).with_for_update())
    if existing:
        if existing.request_hash != payload_hash or existing.merchant_id != merchant_id:
            raise TransactionError("Idempotency key reused for a different request")
        return existing
    row = MpesaPassThroughTransaction(
        merchant_id=merchant_id, application_id=application_id,
        idempotency_key=idempotency_key, request_hash=payload_hash,
        agreement_version=quote.agreement_version, direction=quote.direction,
        currency="LSL", principal=quote.principal, provider_cost=quote.provider_cost,
        platform_fee=quote.ithutepay_fee, funding_amount=quote.funding_amount,
        onward_amount=quote.onward_amount, quote_snapshot=_snapshot(quote),
    )
    db.add(row)
    # Unique database key, not a process lock, is the concurrency safeguard.
    # Concurrent insert races raise IntegrityError and must be retried in a
    # fresh transaction, re-reading the persisted request hash.
    db.flush()
    return row


def find_owned(db: Session, *, merchant_id: str, application_id: str, record_id: str,
               for_update: bool = False) -> MpesaPassThroughTransaction | None:
    statement = select(MpesaPassThroughTransaction).where(
        MpesaPassThroughTransaction.id == record_id,
        MpesaPassThroughTransaction.merchant_id == merchant_id,
        MpesaPassThroughTransaction.application_id == application_id,
    )
    if for_update:
        statement = statement.with_for_update()
    return db.scalar(statement)


def load_lifecycle(row: MpesaPassThroughTransaction) -> PassThrough:
    return _restore(row)


def _write_leg(row: MpesaPassThroughTransaction, name: str, leg: Leg) -> None:
    setattr(row, name + "_status", leg.status.value)
    setattr(row, name + "_reference", leg.reference)
    setattr(row, name + "_provider_id", leg.provider_transaction_id)
    setattr(row, name + "_evidence_hash", leg.evidence_hash)
    row.version += 1


def begin_record_leg(db: Session, *, merchant_id: str, application_id: str,
                     record_id: str, leg: str, reference: str) -> MpesaPassThroughTransaction:
    """Internal state reservation; not an externally accessible dispatch API.

    Production execution must atomically persist operation intent/outbox and
    then dispatch the authorized provider movement after commit.
    """
    row = find_owned(db, merchant_id=merchant_id, application_id=application_id,
                     record_id=record_id, for_update=True)
    if row is None:
        raise TransactionError("Transaction not found in merchant scope")
    updated = begin(_restore(row), leg, reference)
    _write_leg(row, leg, getattr(updated, leg))
    db.flush()
    return row


def record_verified_evidence(
    db: Session, *, merchant_id: str, application_id: str, record_id: str,
    leg: str, reference: str, status: str, provider_transaction_id: str | None,
    evidence: bytes,
) -> MpesaPassThroughTransaction:
    """INTERNAL ONLY: caller must independently verify provider evidence.

    Never expose this function to user-controlled HTTP status parameters.
    """
    row = find_owned(db, merchant_id=merchant_id, application_id=application_id,
                     record_id=record_id, for_update=True)
    if row is None:
        raise TransactionError("Transaction not found in merchant scope")
    updated = observe(_restore(row), leg, reference=reference, status=status,
                      provider_transaction_id=provider_transaction_id, evidence=evidence)
    new_leg = getattr(updated, leg)
    old_leg = getattr(_restore(row), leg)
    if new_leg != old_leg:
        _write_leg(row, leg, new_leg)
        db.flush()
    return row
