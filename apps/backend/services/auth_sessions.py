from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.config.config import settings
from database.models.auth_session import AuthSession
from services.security_service import sha256_text
from utils.decode_encode_token import create_refresh_token, decode_token


def _aware_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def issue_session(db: Session, *, user_id: str, request: Request) -> tuple[AuthSession, str, str]:
    refresh_token, _jti, expires_at = create_refresh_token({'user_id': user_id})
    csrf = secrets.token_urlsafe(32)
    session = AuthSession(
        user_id=user_id,
        refresh_token_hash=sha256_text(refresh_token),
        csrf_token_hash=sha256_text(csrf),
        user_agent=request.headers.get('user-agent', '')[:512] or None,
        ip_address=(request.client.host if request.client else None),
        expires_at=expires_at,
    )
    db.add(session)
    db.flush()
    return session, refresh_token, csrf


def rotate_session(db: Session, *, refresh_token: str, request: Request) -> tuple[AuthSession, str, str]:
    payload = decode_token(refresh_token)
    if payload.get('token_type') != 'refresh':
        raise ValueError('Invalid refresh token type')
    session = db.scalar(select(AuthSession).where(AuthSession.refresh_token_hash == sha256_text(refresh_token)))
    now = datetime.now(timezone.utc)
    if not session or session.revoked_at is not None or _aware_utc(session.expires_at) <= now:
        raise ValueError('Refresh session is invalid')
    session.revoked_at = now
    db.add(session)
    return issue_session(db, user_id=session.user_id, request=request)


def revoke_session(db: Session, refresh_token: str | None) -> None:
    if not refresh_token:
        return
    session = db.scalar(select(AuthSession).where(AuthSession.refresh_token_hash == sha256_text(refresh_token)))
    if session and session.revoked_at is None:
        session.revoked_at = datetime.now(timezone.utc)
        db.add(session)


def purge_expired_sessions(db: Session) -> int:
    from sqlalchemy import delete
    cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    result = db.execute(delete(AuthSession).where(AuthSession.expires_at < cutoff))
    return int(result.rowcount or 0)
