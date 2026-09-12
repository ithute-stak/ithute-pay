from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.security import get_current_user
from database.config.config import settings
from database.models.merchant import ApiKey, Application, Merchant
from database.models.user import User
from database.session import get_db
from services.security_service import sha256_text
from utils.convex import current_application_id, current_merchant_id

merchant_bearer = HTTPBearer(auto_error=False)

PLATFORM_ROLES = {
    'platform_super_admin', 'platform_admin', 'operations', 'finance',
    'developer', 'support', 'compliance', 'auditor',
}
PLATFORM_ADMIN_ROLES = {'platform_super_admin', 'platform_admin', 'operations', 'finance', 'developer'}


@dataclass(frozen=True)
class MerchantContext:
    api_key: ApiKey
    application: Application
    merchant: Merchant


def get_current_active_user(user: User = Depends(get_current_user)) -> User:
    if not user.is_active:
        raise HTTPException(status_code=403, detail='Account is inactive')
    return user


def require_platform_user(user: User = Depends(get_current_active_user)) -> User:
    if str(user.role) not in PLATFORM_ROLES:
        raise HTTPException(status_code=403, detail='Platform role required')
    return user


def require_platform_admin(user: User = Depends(get_current_active_user)) -> User:
    if str(user.role) not in PLATFORM_ADMIN_ROLES:
        raise HTTPException(status_code=403, detail='Platform administrator role required')
    return user


platform_admin = require_platform_admin


async def _verify_request_signature(request: Request, token: str, application_id: str) -> None:
    signature = request.headers.get('x-ipb-signature')
    timestamp = request.headers.get('x-ipb-timestamp')
    nonce = request.headers.get('x-ipb-nonce')
    if not any((signature, timestamp, nonce)) and not settings.API_SIGNATURE_REQUIRED_BY_DEFAULT:
        return
    if not signature or not timestamp or not nonce:
        raise HTTPException(status_code=401, detail='Signed requests require X-IPB-Timestamp, X-IPB-Nonce and X-IPB-Signature')
    try:
        stamp = int(timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail='Invalid request signature timestamp') from exc
    if abs(int(time.time()) - stamp) > settings.API_SIGNATURE_MAX_AGE_SECONDS:
        raise HTTPException(status_code=401, detail='Signed request timestamp is outside the allowed window')
    body = await request.body()
    body_hash = hashlib.sha256(body).hexdigest()
    canonical = f'{timestamp}\n{nonce}\n{request.method.upper()}\n{request.url.path}\n{body_hash}'.encode()
    expected = hmac.new(token.encode(), canonical, hashlib.sha256).hexdigest()
    supplied = signature.removeprefix('sha256=')
    if not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=401, detail='Invalid request signature')
    if settings.REDIS_URL:
        try:
            import redis.asyncio as redis
            client = redis.from_url(settings.REDIS_URL, decode_responses=True)
            accepted = await client.set(
                f'ipb:nonce:{application_id}:{nonce}', '1',
                ex=settings.API_SIGNATURE_MAX_AGE_SECONDS, nx=True,
            )
            await client.aclose()
            if not accepted:
                raise HTTPException(status_code=409, detail='Request nonce has already been used')
        except HTTPException:
            raise
        except Exception:
            # Redis outages must not silently turn into payment duplication. Signed
            # requests still pass HMAC/timestamp validation; financial endpoints also
            # require Idempotency-Key for create operations.
            pass


async def get_merchant_context(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(merchant_bearer),
    db: Session = Depends(get_db),
) -> MerchantContext:
    if credentials is None:
        raise HTTPException(status_code=401, detail='API key required')
    token = credentials.credentials
    if not token.startswith(('ipb_test_', 'ipb_live_')):
        raise HTTPException(status_code=401, detail='Invalid API key')
    key = db.scalar(select(ApiKey).where(ApiKey.secret_hash == sha256_text(token)))
    if not key or key.revoked_at is not None:
        raise HTTPException(status_code=401, detail='Invalid or revoked API key')
    application = db.get(Application, key.application_id)
    if not application or application.status != 'active':
        raise HTTPException(status_code=401, detail='Application inactive')
    merchant = db.get(Merchant, application.merchant_id)
    if not merchant or merchant.status != 'active':
        raise HTTPException(status_code=401, detail='Merchant inactive')
    await _verify_request_signature(request, token, application.id)
    key.last_used_at = datetime.now(timezone.utc)
    db.add(key)
    db.commit()
    current_application_id.set(str(application.id))
    current_merchant_id.set(str(merchant.id))
    return MerchantContext(api_key=key, application=application, merchant=merchant)


merchant_context = get_merchant_context


def idempotency_key(value: str | None = Header(default=None, alias='Idempotency-Key')) -> str:
    if not value or not value.strip():
        raise HTTPException(status_code=400, detail='Idempotency-Key header is required')
    value = value.strip()
    if len(value) > 200:
        raise HTTPException(status_code=400, detail='Idempotency-Key is too long')
    return value


def require_scope(scope: str):
    async def dependency(context: MerchantContext = Depends(get_merchant_context)) -> MerchantContext:
        scopes = set(context.api_key.scopes or [])
        if scopes and '*' not in scopes and scope not in scopes:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f'API key is missing required scope: {scope}')
        return context
    return dependency


current_user = get_current_active_user
