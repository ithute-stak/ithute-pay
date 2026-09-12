from __future__ import annotations

import secrets
from typing import Annotated

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.config.config import settings
from database.models.user import User
from database.session import get_db
from services.ithute_auth import IthuteAuthDisabled, IthuteAuthUnavailable, decode_access_token
from utils.decode_encode_token import create_access_token as _create_access_token, decode_token


oauth2_scheme = OAuth2PasswordBearer(tokenUrl='/api/v1/auth/login', auto_error=False)
password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return password_hasher.verify(hashed_password, plain_password)
    except (VerifyMismatchError, InvalidHashError, ValueError, TypeError):
        return False


def _token_from_request(request: Request, bearer_token: str | None) -> str:
    token = bearer_token or request.cookies.get('ipb_access')
    if not token:
        raise HTTPException(status_code=401, detail='Authentication required')
    return token


def _looks_like_central_token(token: str) -> bool:
    if not settings.ITHUTE_AUTH_ENABLED:
        return False
    try:
        header = jwt.get_unverified_header(token)
        if header.get('alg') != 'RS256':
            return False
        claims = jwt.decode(token, options={'verify_signature': False, 'verify_exp': False, 'verify_aud': False})
    except jwt.PyJWTError:
        return False
    audience = claims.get('aud')
    audience_match = audience == settings.ITHUTE_AUTH_AUDIENCE or (
        isinstance(audience, list) and settings.ITHUTE_AUTH_AUDIENCE in audience
    )
    return claims.get('iss') == settings.ITHUTE_AUTH_ISSUER.rstrip('/') and audience_match


def local_user_from_token(token: str, db: Session) -> User:
    payload = decode_token(token)
    if payload.get('token_type') != 'access':
        raise HTTPException(status_code=401, detail='Invalid local access token type')
    raw_user_id = payload.get('user_id') or payload.get('sub')
    if not raw_user_id:
        raise HTTPException(status_code=401, detail='Invalid local access token')
    user = db.get(User, str(raw_user_id))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail='User account is unavailable')
    return user


def _project_platform_owner(claims: dict, db: Session) -> User:
    """Project the signed central owner into Pay without copying its password."""
    subject = str(claims['sub'])
    email = str(claims.get('email') or '').strip().lower()
    if not email:
        raise HTTPException(status_code=401, detail='Central platform owner token is missing an email claim')

    user = db.scalar(select(User).where(User.auth_user_id == subject))
    if user is None:
        user = db.scalar(select(User).where(User.email == email))
        if user is not None and user.auth_user_id not in (None, subject):
            raise HTTPException(status_code=409, detail='The system owner email is linked to another central identity')

    if user is None:
        # Pay's legacy schema still requires a password_hash. Use an unrecoverable
        # product-local random value, never the central system-owner password.
        user = User(
            auth_user_id=subject,
            email=email,
            password_hash=hash_password(secrets.token_urlsafe(48)),
            full_name='Ithute System Owner',
            role='platform_super_admin',
            is_active=True,
        )
        db.add(user)
    else:
        user.auth_user_id = subject
        user.role = 'platform_super_admin'
        user.is_active = True
        if not user.full_name.strip():
            user.full_name = 'Ithute System Owner'

    db.commit()
    db.refresh(user)
    return user


def central_user_from_token(token: str, db: Session) -> User:
    try:
        claims = decode_access_token(token)
    except IthuteAuthDisabled as exc:
        raise HTTPException(status_code=401, detail='Central authentication is disabled') from exc
    except IthuteAuthUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail='!thute Auth verification is temporarily unavailable',
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail='Invalid !thute Auth token') from exc

    if claims.get('is_platform_admin') is True:
        return _project_platform_owner(claims, db)

    user = db.scalar(select(User).where(User.auth_user_id == str(claims['sub'])))
    if not user or not user.is_active:
        raise HTTPException(
            status_code=401,
            detail={
                'code': 'ITHUTE_ACCOUNT_NOT_LINKED',
                'message': 'This !thute account is not linked to an Ithute Pay user.',
            },
        )
    return user


def get_current_local_user(
    request: Request,
    bearer_token: Annotated[str | None, Depends(oauth2_scheme)] = None,
    db: Session = Depends(get_db),
) -> User:
    token = _token_from_request(request, bearer_token)
    if _looks_like_central_token(token):
        raise HTTPException(status_code=401, detail='A current Ithute Pay local session is required for this migration action')
    return local_user_from_token(token, db)


def get_current_user(
    request: Request,
    bearer_token: Annotated[str | None, Depends(oauth2_scheme)] = None,
    db: Session = Depends(get_db),
) -> User:
    token = _token_from_request(request, bearer_token)
    if _looks_like_central_token(token):
        return central_user_from_token(token, db)
    return local_user_from_token(token, db)


def central_access_token_from_request(request: Request) -> str:
    raw = request.headers.get('authorization')
    token = ''
    if raw:
        scheme, _, value = raw.partition(' ')
        if scheme.lower() == 'bearer':
            token = value.strip()
    if not token:
        token = request.cookies.get('ipb_access') or ''
    if not token or not _looks_like_central_token(token):
        raise HTTPException(
            status_code=409,
            detail='A linked !thute Auth session is required for central push device registration',
        )
    # Verify signature/audience before forwarding the token to !thute Push.
    try:
        decode_access_token(token)
    except (IthuteAuthDisabled, IthuteAuthUnavailable, jwt.InvalidTokenError) as exc:
        raise HTTPException(status_code=401, detail='Invalid !thute Auth session') from exc
    return token


def create_access_token(subject: str | dict, *, extra: dict | None = None) -> str:
    payload = dict(subject) if isinstance(subject, dict) else {'user_id': str(subject)}
    if extra:
        payload.update(extra)
    payload.setdefault('token_type', 'access')
    return _create_access_token(payload)


def authenticate_user(user: User) -> str:
    return create_access_token(
        str(user.id),
        extra={'role': str(user.role), 'token_type': 'access'},
    )


from services.security_service import generate_secret, sha256_text, verify_secret, webhook_signature  # noqa: E402
