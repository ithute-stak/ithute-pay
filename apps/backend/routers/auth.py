from __future__ import annotations

import secrets
from datetime import timedelta
from urllib.parse import quote

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse, RedirectResponse

from core.access_control import get_current_active_user
from core.security import authenticate_user, get_current_local_user, hash_password, local_user_from_token, verify_password
from database.config.config import settings
from database.models.audit_log import AuditLog
from database.models.user import User
from database.schemas.auth import LoginRequest, MeResponse, RefreshResponse, TokenResponse, WebSocketSessionResponse
from database.session import get_db
from services.auth_sessions import issue_session, revoke_session, rotate_session
from services.ithute_auth import (
    IthuteAuthDisabled,
    IthuteAuthUnavailable,
    authorization_url,
    decode_access_token,
    decode_id_token,
    exchange_code,
    new_oidc_state,
    refresh_access,
    revoke_refresh,
)
from utils.decode_encode_token import create_token


router = APIRouter(prefix='/auth', tags=['Authentication'])
WS_SESSION_COOKIE = 'ipb_ws_session'
CENTRAL_REFRESH_COOKIE = 'ipb_ithute_refresh'
OIDC_COOKIE_PATH = '/api/v1/auth/ithute'
OIDC_STATE_COOKIE = 'ipb_oidc_state'
OIDC_VERIFIER_COOKIE = 'ipb_oidc_verifier'
OIDC_NONCE_COOKIE = 'ipb_oidc_nonce'
OIDC_MODE_COOKIE = 'ipb_oidc_mode'
SYSTEM_OWNER_ROLE = 'platform_super_admin'


def _common_cookie() -> dict:
    return dict(secure=settings.cookie_secure, samesite=settings.COOKIE_SAMESITE, domain=settings.COOKIE_DOMAIN)


def _set_auth_cookies(response: Response, access: str, refresh: str, csrf: str) -> None:
    common = _common_cookie()
    response.set_cookie('ipb_access', access, httponly=True, max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60, path='/', **common)
    response.set_cookie('ipb_refresh', refresh, httponly=True, max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400, path='/api/v1/auth', **common)
    response.set_cookie('ipb_csrf', csrf, httponly=False, max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400, path='/', **common)
    response.delete_cookie(CENTRAL_REFRESH_COOKIE, path='/api/v1/auth', domain=settings.COOKIE_DOMAIN)


def _set_central_auth_cookies(response: Response, access: str, refresh: str, expires_in: int) -> None:
    common = _common_cookie()
    csrf = secrets.token_urlsafe(32)
    response.set_cookie('ipb_access', access, httponly=True, max_age=max(60, expires_in), path='/', **common)
    response.set_cookie(CENTRAL_REFRESH_COOKIE, refresh, httponly=True, max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400, path='/api/v1/auth', **common)
    response.set_cookie('ipb_csrf', csrf, httponly=False, max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400, path='/', **common)
    response.delete_cookie('ipb_refresh', path='/api/v1/auth', domain=settings.COOKIE_DOMAIN)


def _clear_auth_cookies(response: Response) -> None:
    for name, path in [
        ('ipb_access', '/'),
        ('ipb_refresh', '/api/v1/auth'),
        (CENTRAL_REFRESH_COOKIE, '/api/v1/auth'),
        ('ipb_csrf', '/'),
        (WS_SESSION_COOKIE, '/api/v1/ws'),
    ]:
        response.delete_cookie(name, path=path, domain=settings.COOKIE_DOMAIN)


def _set_oidc_cookies(response: Response, *, verifier: str, state: str, nonce: str, mode: str) -> None:
    common = _common_cookie()
    for name, value in [
        (OIDC_STATE_COOKIE, state),
        (OIDC_VERIFIER_COOKIE, verifier),
        (OIDC_NONCE_COOKIE, nonce),
        (OIDC_MODE_COOKIE, mode),
    ]:
        response.set_cookie(name, value, httponly=True, max_age=600, path=OIDC_COOKIE_PATH, **common)


def _clear_oidc_cookies(response: Response) -> None:
    for name in [OIDC_STATE_COOKIE, OIDC_VERIFIER_COOKIE, OIDC_NONCE_COOKIE, OIDC_MODE_COOKIE]:
        response.delete_cookie(name, path=OIDC_COOKIE_PATH, domain=settings.COOKIE_DOMAIN)


def _login_redirect_error(code: str) -> RedirectResponse:
    return RedirectResponse(f'/login?error={quote(code)}', status_code=303)


def _claim_email(claims: dict) -> str:
    return str(claims.get('email') or '').strip().lower()


def _project_system_owner(
    db: Session,
    *,
    central_sub: str,
    access_claims: dict,
    id_claims: dict,
) -> User | None:
    """Project the one signed central system owner into Ithute Pay.

    Normal central users still require an explicit product-local link. Only a
    token pair that independently carries the protected ``is_platform_admin``
    claim in both the access and ID token can enter this path.
    """
    if access_claims.get('is_platform_admin') is not True or id_claims.get('is_platform_admin') is not True:
        return None

    access_email = _claim_email(access_claims)
    id_email = _claim_email(id_claims)
    if not access_email or access_email != id_email:
        return None

    linked_user = db.scalar(select(User).where(User.auth_user_id == central_sub))
    email_user = db.scalar(select(User).where(User.email == id_email))

    # Never collapse two product rows or steal a row already linked to another
    # central identity. Those cases require an explicit administrative repair.
    if linked_user is not None and email_user is not None and linked_user.id != email_user.id:
        return None

    user = linked_user or email_user
    if user is not None and user.auth_user_id not in (None, central_sub):
        return None

    changed = False
    if user is None:
        display_name = str(id_claims.get('name') or '').strip() or 'Ithute System Owner'
        user = User(
            auth_user_id=central_sub,
            email=id_email,
            password_hash=hash_password(secrets.token_urlsafe(48)),
            full_name=display_name,
            role=SYSTEM_OWNER_ROLE,
            is_active=True,
        )
        db.add(user)
        db.flush()
        changed = True
    else:
        if user.auth_user_id != central_sub:
            user.auth_user_id = central_sub
            changed = True
        if user.role != SYSTEM_OWNER_ROLE:
            user.role = SYSTEM_OWNER_ROLE
            changed = True
        if not user.is_active:
            user.is_active = True
            changed = True
        if not user.full_name.strip():
            user.full_name = str(id_claims.get('name') or '').strip() or 'Ithute System Owner'
            changed = True

    if changed:
        db.add(
            AuditLog(
                actor_type='user',
                actor_id=user.id,
                action='auth.ithute.system_owner_projected',
                resource_type='user',
                resource_id=user.id,
                metadata_json={'auth_user_id': central_sub, 'central_email': id_email},
            )
        )
        db.commit()
        db.refresh(user)

    return user


def _oidc_parameters(mode: str) -> tuple[str, str, str, str, str]:
    try:
        verifier, challenge, state, nonce = new_oidc_state()
        target = authorization_url(state=state, nonce=nonce, code_challenge=challenge)
    except IthuteAuthDisabled as exc:
        raise HTTPException(status_code=503, detail='!thute Auth is not enabled for Ithute Pay') from exc
    return verifier, state, nonce, mode, target


def _start_oidc_redirect(mode: str) -> RedirectResponse:
    verifier, state, nonce, mode, target = _oidc_parameters(mode)
    response = RedirectResponse(target, status_code=303)
    _set_oidc_cookies(response, verifier=verifier, state=state, nonce=nonce, mode=mode)
    return response


@router.post('/login', response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> TokenResponse:
    if not settings.ITHUTE_AUTH_LEGACY_LOGIN_ENABLED:
        raise HTTPException(
            status_code=410,
            detail='Local Ithute Pay login has been retired. Sign in with !thute Auth.',
        )
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail='Invalid email or password')
    if not user.is_active:
        raise HTTPException(status_code=403, detail='Account is inactive')
    access = authenticate_user(user)
    _session, refresh, csrf = issue_session(db, user_id=user.id, request=request)
    db.commit()
    _set_auth_cookies(response, access, refresh, csrf)
    return TokenResponse(access_token=access, expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)


@router.get('/ithute/start')
def ithute_start():
    # Starting a normal login does not mutate an existing product identity and
    # may safely use a browser navigation GET.
    return _start_oidc_redirect('login')


@router.post('/ithute/link/start')
def ithute_link_start(_: User = Depends(get_current_local_user)):
    # Linking is sensitive. It is POST-only so CSRFMiddleware verifies the
    # double-submit token before any central-account linking flow can start.
    verifier, state, nonce, mode, target = _oidc_parameters('link')
    response = JSONResponse({'authorization_url': target})
    _set_oidc_cookies(response, verifier=verifier, state=state, nonce=nonce, mode=mode)
    return response


@router.get('/ithute/callback')
def ithute_callback(
    request: Request,
    code: str = Query(min_length=20, max_length=1024),
    state: str = Query(min_length=16, max_length=512),
    db: Session = Depends(get_db),
):
    expected_state = request.cookies.get(OIDC_STATE_COOKIE) or ''
    verifier = request.cookies.get(OIDC_VERIFIER_COOKIE) or ''
    nonce = request.cookies.get(OIDC_NONCE_COOKIE) or ''
    mode = request.cookies.get(OIDC_MODE_COOKIE) or 'login'
    if not expected_state or not secrets.compare_digest(expected_state, state) or not verifier or not nonce:
        response = _login_redirect_error('central_state_invalid')
        _clear_oidc_cookies(response)
        return response

    try:
        payload = exchange_code(code=code, code_verifier=verifier)
        access = str(payload['access_token'])
        refresh = str(payload['refresh_token'])
        access_claims = decode_access_token(access)
        id_claims = decode_id_token(str(payload['id_token']), nonce=nonce)
        if str(access_claims['sub']) != str(id_claims['sub']) or str(access_claims['sid']) != str(id_claims['sid']):
            raise jwt.InvalidTokenError('access/id token identity mismatch')
        if bool(access_claims.get('is_platform_admin')) != bool(id_claims.get('is_platform_admin')):
            raise jwt.InvalidTokenError('access/id token platform-admin mismatch')
    except IthuteAuthDisabled:
        response = _login_redirect_error('central_auth_disabled')
        _clear_oidc_cookies(response)
        return response
    except IthuteAuthUnavailable:
        response = _login_redirect_error('central_auth_unavailable')
        _clear_oidc_cookies(response)
        return response
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        response = _login_redirect_error('central_token_invalid')
        _clear_oidc_cookies(response)
        return response

    central_sub = str(access_claims['sub'])
    linked_user = db.scalar(select(User).where(User.auth_user_id == central_sub))

    if mode == 'login':
        projected_owner = _project_system_owner(
            db,
            central_sub=central_sub,
            access_claims=access_claims,
            id_claims=id_claims,
        )
        if projected_owner is not None:
            linked_user = projected_owner

    if mode == 'link':
        local_token = request.cookies.get('ipb_access') or ''
        try:
            current = local_user_from_token(local_token, db)
        except HTTPException:
            response = _login_redirect_error('local_session_required_for_link')
            _clear_oidc_cookies(response)
            return response
        if linked_user is not None and linked_user.id != current.id:
            response = _login_redirect_error('central_account_already_linked')
            _clear_oidc_cookies(response)
            return response
        if current.auth_user_id and current.auth_user_id != central_sub:
            response = _login_redirect_error('local_account_already_linked')
            _clear_oidc_cookies(response)
            return response
        current.auth_user_id = central_sub
        db.add(
            AuditLog(
                actor_type='user',
                actor_id=current.id,
                action='auth.ithute.link',
                resource_type='user',
                resource_id=current.id,
                metadata_json={'auth_user_id': central_sub},
            )
        )
        db.commit()
        linked_user = current

    if linked_user is None or not linked_user.is_active:
        response = _login_redirect_error('central_account_not_linked')
        _clear_oidc_cookies(response)
        return response

    response = RedirectResponse('/dashboard', status_code=303)
    _set_central_auth_cookies(
        response,
        access,
        refresh,
        int(payload.get('expires_in') or 600),
    )
    _clear_oidc_cookies(response)
    return response


@router.get('/ithute/status')
def ithute_status(user: User = Depends(get_current_active_user)):
    return {
        'enabled': settings.ITHUTE_AUTH_ENABLED,
        'legacy_login_enabled': settings.ITHUTE_AUTH_LEGACY_LOGIN_ENABLED,
        'linked': bool(user.auth_user_id),
        'auth_user_id': user.auth_user_id,
        'client_id': settings.ITHUTE_AUTH_AUDIENCE,
    }


@router.post('/refresh', response_model=RefreshResponse)
def refresh(request: Request, response: Response, db: Session = Depends(get_db)) -> RefreshResponse:
    central_refresh = request.cookies.get(CENTRAL_REFRESH_COOKIE)
    if central_refresh:
        try:
            payload = refresh_access(central_refresh)
        except (IthuteAuthDisabled, IthuteAuthUnavailable, jwt.InvalidTokenError) as exc:
            raise HTTPException(status_code=401, detail='Central session refresh failed') from exc
        access = str(payload['access_token'])
        new_refresh = str(payload['refresh_token'])
        _set_central_auth_cookies(response, access, new_refresh, int(payload.get('expires_in') or 600))
        return RefreshResponse(access_token=access, expires_in=int(payload.get('expires_in') or 600))

    refresh_token = request.cookies.get('ipb_refresh')
    if not refresh_token:
        raise HTTPException(status_code=401, detail='Refresh token missing')
    try:
        session, new_refresh, csrf = rotate_session(db, refresh_token=refresh_token, request=request)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    user = db.get(User, session.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail='User unavailable')
    access = authenticate_user(user)
    db.commit()
    _set_auth_cookies(response, access, new_refresh, csrf)
    return RefreshResponse(access_token=access, expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)


@router.post('/logout')
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    local_refresh = request.cookies.get('ipb_refresh')
    if local_refresh:
        revoke_session(db, local_refresh)
        db.commit()
    revoke_refresh(request.cookies.get(CENTRAL_REFRESH_COOKIE) or '')
    _clear_auth_cookies(response)
    return {'message': 'Signed out'}


@router.get('/me', response_model=MeResponse)
def me(user: User = Depends(get_current_active_user)) -> MeResponse:
    return MeResponse.model_validate(user)


@router.post('/websocket-session', response_model=WebSocketSessionResponse)
def create_websocket_session(current_user: User = Depends(get_current_active_user)):
    token = create_token(
        {'user_id': str(current_user.id), 'role': current_user.role, 'token_type': 'websocket'},
        timedelta(seconds=settings.WEBSOCKET_SESSION_TTL_SECONDS),
    )
    response = JSONResponse(WebSocketSessionResponse(expires_in=settings.WEBSOCKET_SESSION_TTL_SECONDS).model_dump(mode='json'))
    response.set_cookie(
        key=WS_SESSION_COOKIE,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.COOKIE_SAMESITE,
        max_age=settings.WEBSOCKET_SESSION_TTL_SECONDS,
        path='/api/v1/ws',
        domain=settings.COOKIE_DOMAIN,
    )
    return response
