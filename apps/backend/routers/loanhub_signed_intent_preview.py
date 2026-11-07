"""Disabled-by-default, signed, non-posting LoanHub collection-intent preview.

The POST body is authenticated byte-for-byte. No payment intent is persisted,
no idempotency key is reserved, and no provider or financial APIs are called.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import time
from collections.abc import Callable
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.config.config import settings
from database.models import (
    ApiKey, Application, GatewayProviderConfiguration, Merchant, PlatformMerchantSettings,
)
from database.session import get_db
from routers.loanhub_intent_preview import (
    CollectionIntentPreviewInput, build_collection_intent_preview,
)
from routers.loanhub_master_binding import (
    APPLICATION_NAME, LOANHUB_COMPANY_ID, MASTER_MERCHANT_ID,
    PROVIDER_CONFIGURATION_ID,
)
from routers.loanhub_signed_handshake import (
    MAX_AGE_SECONDS, NONCE_PATTERN, claim_handshake_nonce,
)

router = APIRouter(prefix="/integrations/loanhub", tags=["LoanHub Integration"])
PREVIEW_PATH = "/api/v1/integrations/loanhub/batlokoa/collection-intent-preview"
MAX_BODY_BYTES = 4096


def verify_signed_preview(
    *,
    secret: str,
    company_id: str | None,
    timestamp: str | None,
    nonce: str | None,
    signature: str | None,
    raw_body: bytes,
    now: int,
    claim_nonce: Callable[[str], bool],
) -> None:
    """Validate a unique POST signature, including SHA-256 of the exact body."""
    if not isinstance(secret, str) or len(secret) < 32:
        raise ValueError("Unconfigured preview secret")
    if company_id != LOANHUB_COMPANY_ID:
        raise ValueError("Unknown company")
    if not timestamp or not timestamp.isdecimal() or len(timestamp) > 12:
        raise ValueError("Invalid timestamp")
    if abs(now - int(timestamp)) > MAX_AGE_SECONDS:
        raise ValueError("Expired timestamp")
    if not nonce or not NONCE_PATTERN.fullmatch(nonce):
        raise ValueError("Invalid nonce")
    if not signature or not re.fullmatch(r"[0-9a-fA-F]{64}", signature):
        raise ValueError("Invalid signature")
    if len(raw_body) > MAX_BODY_BYTES:
        raise ValueError("Oversized body")
    body_hash = hashlib.sha256(raw_body).hexdigest()
    msg = (
        f"{timestamp}\n{nonce}\nPOST\n{PREVIEW_PATH}\n"
        f"{company_id}\n{body_hash}"
    ).encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature.lower()):
        raise ValueError("Invalid signature")
    # Shared Redis nonce namespace: uniqueness spans handshake and preview.
    if not claim_nonce(nonce):
        raise ValueError("Replayed nonce")


@router.post("/batlokoa/collection-intent-preview")
async def signed_batlokoa_collection_intent_preview(
    request: Request,
    x_loanhub_company_id: str | None = Header(default=None),
    x_loanhub_timestamp: str | None = Header(default=None),
    x_loanhub_nonce: str | None = Header(default=None),
    x_loanhub_signature: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    if not settings.LOANHUB_BATLOKOA_INTENT_PREVIEW_ENABLED:
        raise HTTPException(status_code=404, detail="Integration preview unavailable")
    if request.url.path != PREVIEW_PATH:
        raise HTTPException(status_code=404, detail="Unexpected integration path")
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise HTTPException(status_code=415, detail="JSON content required")
    # Reject excessively large bodies before calculating a signature.
    if request.headers.get("content-length", "").isdecimal():
        if int(request.headers["content-length"]) > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Preview request too large")
    raw_body = await request.body()
    if len(raw_body) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Preview request too large")
    try:
        verify_signed_preview(
            secret=settings.LOANHUB_BATLOKOA_HANDSHAKE_SECRET,
            company_id=x_loanhub_company_id,
            timestamp=x_loanhub_timestamp,
            nonce=x_loanhub_nonce,
            signature=x_loanhub_signature,
            raw_body=raw_body,
            now=int(time.time()),
            claim_nonce=claim_handshake_nonce,
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid integration signature") from exc
    try:
        payload = CollectionIntentPreviewInput.model_validate_json(raw_body)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="Invalid collection preview input") from exc

    master = db.scalar(select(PlatformMerchantSettings).where(
        PlatformMerchantSettings.active.is_(True),
    ))
    merchant = db.get(Merchant, MASTER_MERCHANT_ID)
    gateway = db.get(GatewayProviderConfiguration, PROVIDER_CONFIGURATION_ID)
    apps = db.scalars(select(Application).where(
        Application.name == APPLICATION_NAME,
    )).all()
    key_count = 0
    if len(apps) == 1:
        key_count = len(db.scalars(select(ApiKey.id).where(
            ApiKey.application_id == apps[0].id,
        )).all())
    try:
        return build_collection_intent_preview(
            master=master, merchant=merchant, gateway=gateway,
            applications=apps, api_key_count=key_count, payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="Integration not ready") from exc
