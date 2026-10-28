"""Receive and durably stage verified Golink webhook messages.

Intentionally does NOT mark financial transactions succeeded. A separate
reconciliation worker must query Golink and verify the original payment.
"""
from __future__ import annotations

import json
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.models import ProviderCallbackLog
from database.session import get_db
from providers.golink.webhooks import InvalidGolinkSignature, verify_golink_signature, extract_payment_id

router = APIRouter(prefix="/provider-callbacks/golink", tags=["Golink callbacks"])


@router.post("")
async def receive_golink_webhook(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    if len(raw) > 256 * 1024:
        raise HTTPException(status_code=413, detail="Payload too large")
    secret = os.environ.get("GOLINK_WEBHOOK_SECRET", "")
    try:
        fingerprint = verify_golink_signature(
            raw, request.headers.get("X-Golink-Signature"), secret
        )
    except InvalidGolinkSignature:
        raise HTTPException(status_code=401, detail="Invalid webhook signature") from None
    try:
        event = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Invalid JSON") from None
    if not isinstance(event, dict) or not isinstance(event.get("type"), str):
        raise HTTPException(status_code=422, detail="Invalid event shape")
    if event["type"] not in {
        "payment.created", "payment.succeeded", "payment.failed",
        "payment.cancelled", "payment.refunded",
    }:
        raise HTTPException(status_code=422, detail="Unsupported webhook event")

    try:
        extract_payment_id(event)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid payment identity") from None

    # Persist before ACK; the unique constraint prevents identical event replay.
    # The callback log's callback_type is a fixed string to stay within String(30).
    db.add(ProviderCallbackLog(
        provider="golink", callback_type="outbound_webhook",
        payload_hash=fingerprint, raw_payload=event,
        processing_status="received",
    ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Fail closed unless the conflict is demonstrably an identical webhook.
        # A different integrity violation must never be acknowledged as delivered.
        existing = db.scalar(select(ProviderCallbackLog.id).where(
            ProviderCallbackLog.provider == "golink",
            ProviderCallbackLog.callback_type == "outbound_webhook",
            ProviderCallbackLog.payload_hash == fingerprint,
        ))
        if existing is None:
            raise
        return {"received": True, "duplicate": True}
    return {"received": True}
