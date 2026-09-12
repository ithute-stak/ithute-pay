from __future__ import annotations

import base64
import hashlib
import secrets
from functools import lru_cache
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

import httpx
import jwt
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError

from database.config.config import settings


class IthuteAuthDisabled(RuntimeError):
    pass


class IthuteAuthUnavailable(RuntimeError):
    pass


@lru_cache(maxsize=4)
def _jwks_client(url: str) -> PyJWKClient:
    return PyJWKClient(url)


def issuer() -> str:
    return settings.ITHUTE_AUTH_ISSUER.rstrip('/')


def jwks_url() -> str:
    return settings.ITHUTE_AUTH_JWKS_URL or f'{issuer()}/.well-known/jwks.json'


def redirect_uri() -> str:
    configured = (settings.ITHUTE_AUTH_REDIRECT_URI or '').strip()
    if configured:
        return configured
    return f"{settings.PUBLIC_APP_URL.rstrip('/')}/api/v1/auth/ithute/callback"


def ensure_enabled() -> None:
    if not settings.ITHUTE_AUTH_ENABLED:
        raise IthuteAuthDisabled('!thute Auth is disabled for Ithute Pay')


def _decode(
    token: str,
    *,
    token_use: str,
    nonce: str | None = None,
    jwks_client: Any | None = None,
) -> dict[str, Any]:
    ensure_enabled()
    client = jwks_client or _jwks_client(jwks_url())
    try:
        signing_key = client.get_signing_key_from_jwt(token).key
    except PyJWKClientConnectionError as exc:
        raise IthuteAuthUnavailable('!thute Auth signing keys are unavailable') from exc
    except PyJWKClientError as exc:
        raise jwt.InvalidTokenError('unknown or invalid !thute Auth signing key') from exc

    required = ['iss', 'sub', 'aud', 'sid', 'iat', 'exp', 'token_use']
    if token_use == 'access':
        required.append('nbf')
    if token_use == 'id':
        required.append('nonce')

    claims = jwt.decode(
        token,
        signing_key,
        algorithms=['RS256'],
        issuer=issuer(),
        audience=settings.ITHUTE_AUTH_AUDIENCE,
        options={'require': required},
    )
    if claims.get('token_use') != token_use:
        raise jwt.InvalidTokenError(f'wrong !thute Auth token type: expected {token_use}')
    try:
        UUID(str(claims['sub']))
        UUID(str(claims['sid']))
    except (KeyError, TypeError, ValueError) as exc:
        raise jwt.InvalidTokenError('invalid !thute Auth identity claims') from exc
    if nonce is not None and not secrets.compare_digest(str(claims.get('nonce') or ''), nonce):
        raise jwt.InvalidTokenError('invalid !thute Auth nonce')
    return claims


def decode_access_token(token: str, *, jwks_client: Any | None = None) -> dict[str, Any]:
    return _decode(token, token_use='access', jwks_client=jwks_client)


def decode_id_token(token: str, *, nonce: str, jwks_client: Any | None = None) -> dict[str, Any]:
    return _decode(token, token_use='id', nonce=nonce, jwks_client=jwks_client)


def new_oidc_state() -> tuple[str, str, str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).rstrip(b'=').decode('ascii')
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    return verifier, challenge, state, nonce


def authorization_url(*, state: str, nonce: str, code_challenge: str) -> str:
    ensure_enabled()
    query = urlencode(
        {
            'response_type': 'code',
            'client_id': settings.ITHUTE_AUTH_AUDIENCE,
            'redirect_uri': redirect_uri(),
            'code_challenge': code_challenge,
            'code_challenge_method': 'S256',
            'scope': 'openid profile email phone',
            'state': state,
            'nonce': nonce,
        }
    )
    return f'{issuer()}/oauth/authorize?{query}'


def exchange_code(*, code: str, code_verifier: str) -> dict[str, Any]:
    ensure_enabled()
    try:
        response = httpx.post(
            f'{issuer()}/oauth/token',
            data={
                'grant_type': 'authorization_code',
                'client_id': settings.ITHUTE_AUTH_AUDIENCE,
                'code': code,
                'redirect_uri': redirect_uri(),
                'code_verifier': code_verifier,
            },
            timeout=settings.ITHUTE_AUTH_HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise IthuteAuthUnavailable('Unable to exchange !thute authorization code') from exc
    if not isinstance(payload, dict) or not payload.get('access_token') or not payload.get('refresh_token') or not payload.get('id_token'):
        raise IthuteAuthUnavailable('!thute Auth returned an incomplete token response')
    return payload


def refresh_access(refresh_token: str) -> dict[str, Any]:
    ensure_enabled()
    try:
        response = httpx.post(
            f'{issuer()}/oauth/token',
            data={
                'grant_type': 'refresh_token',
                'client_id': settings.ITHUTE_AUTH_AUDIENCE,
                'refresh_token': refresh_token,
            },
            timeout=settings.ITHUTE_AUTH_HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise IthuteAuthUnavailable('Unable to refresh !thute session') from exc
    if not isinstance(payload, dict) or not payload.get('access_token') or not payload.get('refresh_token'):
        raise IthuteAuthUnavailable('!thute Auth returned an incomplete refresh response')
    decode_access_token(str(payload['access_token']))
    return payload


def revoke_refresh(refresh_token: str) -> None:
    if not refresh_token or not settings.ITHUTE_AUTH_ENABLED:
        return
    try:
        httpx.post(
            f'{issuer()}/v1/auth/logout',
            json={'refresh_token': refresh_token},
            timeout=settings.ITHUTE_AUTH_HTTP_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError:
        # Product logout must still clear its own cookies if central Auth is temporarily unavailable.
        return
