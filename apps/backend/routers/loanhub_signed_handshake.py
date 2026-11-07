"""Disabled-by-default signed, read-only LoanHub/Batlokoa integration handshake.

Separate from merchant payment APIs and shared custody. Requires a dedicated
server-to-server secret and Redis replay defense; fails closed on any outage.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import time
from collections.abc import Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.config.config import settings
from database.models import (
    ApiKey, Application, GatewayProviderConfiguration, Merchant, PlatformMerchantSettings,
)
from database.session import get_db
from routers.loanhub_master_binding import (
    APPLICATION_NAME, LOANHUB_COMPANY_ID, MASTER_MERCHANT_ID,
    PROVIDER_CONFIGURATION_ID, binding_status,
)

router = APIRouter(prefix="/integrations/loanhub", tags=["LoanHub Integration"])

MAX_AGE_SECONDS = 120
SIGNATURE_PATH = "/api/v1/integrations/loanhub/batlokoa/handshake"
NONCE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{24,128}$")


def verify_handshake_signature(
    *,
    secret: str,
    timestamp: str | None,
    nonce: str | None,
    signature: str | None,
    company_id: str | None,
    now: int,
    claim_nonce: Callable[[str], bool],
) -> None:
    """HMAC authenticates the company claim; nonce must be atomically single-use."""
    if len(secret) < 32:
        raise ValueError("Server-to-server handshake secret not configured")
    if not timestamp or not nonce or not signature or not company_id:
        raise ValueError("Signed handshake headers required")
    if company_id != LOANHUB_COMPANY_ID:
        raise ValueError("Unrecognized LoanHub company")
    if not timestamp.isdecimal() or len(timestamp) > 12:
        raise ValueError("Invalid timestamp")
    stamp = int(timestamp)
    if abs(now - stamp) > MAX_AGE_SECONDS:
        raise ValueError("Expired handshake timestamp")
    if not NONCE_PATTERN.fullmatch(nonce):
        raise ValueError("Invalid nonce")
    if not re.fullmatch(r"(?:sha256=)?[0-9a-fA-F]{64}", signature):
        raise ValueError("Malformed signature")
    message = f"{timestamp}\n{nonce}\nGET\n{SIGNATURE_PATH}\n{company_id}".encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature.removeprefix("sha256=").lower()):
        raise ValueError("Invalid handshake signature")
    # Caller must atomically claim the nonce; never allow requests through on
    # replay-store failure. A replay or unavailable Redis rejects the handshake.
    if not claim_nonce(nonce):
        raise ValueError("Handshake nonce already used")


def claim_handshake_nonce(nonce: str) -> bool:
    if not settings.REDIS_URL:
        raise ValueError("Replay protection requires Redis")
    try:
        import redis
        client = redis.Redis.from_url(
            settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2,
            decode_responses=True,
        )
        try:
            return bool(client.set(
                f"loanhub:batlokoa:handshake:nonce:{nonce}", "1",
                ex=MAX_AGE_SECONDS * 2, nx=True,
            ))
        finally:
            client.close()
    except Exception as exc:
        raise ValueError("Replay protection unavailable") from exc


@router.get("/batlokoa/handshake")
def batlokoa_handshake(
    request: Request,
    x_loanhub_company_id: str | None = Header(default=None),
    x_loanhub_timestamp: str | None = Header(default=None),
    x_loanhub_nonce: str | None = Header(default=None),
    x_loanhub_signature: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    if not settings.LOANHUB_BATLOKOA_HANDSHAKE_ENABLED:
        raise HTTPException(status_code=404, detail="Integration handshake unavailable")
    if request.url.path != SIGNATURE_PATH:
        raise HTTPException(status_code=404, detail="Unexpected handshake route")
    try:
        verify_handshake_signature(
            secret=settings.LOANHUB_BATLOKOA_HANDSHAKE_SECRET,
            timestamp=x_loanhub_timestamp,
            nonce=x_loanhub_nonce,
            signature=x_loanhub_signature,
            company_id=x_loanhub_company_id,
            now=int(time.time()),
            claim_nonce=claim_handshake_nonce,
        )
    except ValueError as exc:
        # Avoid disclosing whether a company ID, secret, or nonce was valid.
        raise HTTPException(status_code=401, detail="Invalid integration handshake") from exc

    master = db.scalar(select(PlatformMerchantSettings).where(
        PlatformMerchantSettings.active.is_(True),
    ))
    merchant = db.get(Merchant, MASTER_MERCHANT_ID)
    gateway = db.get(GatewayProviderConfiguration, PROVIDER_CONFIGURATION_ID)
    apps = db.scalars(select(Application).where(
        Application.name == APPLICATION_NAME
    )).all()
    keys = 0
    if len(apps) == 1:
        keys = len(db.scalars(select(ApiKey.id).where(
            ApiKey.application_id == apps[0].id,
        )).all())
    try:
        state = binding_status(master, merchant, gateway, apps, keys)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="Integration not ready") from exc
    # No payment tokens, API credentials, balances, account ownership claims,
    # or PII. Confirmation of registered integration status only.
    return {
        "integration": "loanhub-batlokoa",
        "authenticated": True,
        "company_id": state["loanhub_company_id"],
        "application_id": state["application_id"],
        "merchant_id": state["master_merchant_id"],
        "mpesa_shortcode": state["mpesa_shortcode"],
        "application_status": state["application_status"],
        "payment_routing_enabled": False,
        "shared_custody_enabled": False,
        "fee_enforcement_enabled": False,
    }
