from __future__ import annotations

import threading
import time
from typing import Any
from urllib.parse import quote

import httpx

from database.config.config import settings


class IthutePushDisabled(RuntimeError):
    pass


class IthutePushUnavailable(RuntimeError):
    pass


_token_lock = threading.Lock()
_cached_service_token = ''
_cached_service_token_until = 0.0


def _push_url(path: str) -> str:
    return f"{settings.ITHUTE_PUSH_URL.rstrip('/')}/{path.lstrip('/')}"


def _auth_url(path: str) -> str:
    return f"{settings.ITHUTE_AUTH_ISSUER.rstrip('/')}/{path.lstrip('/')}"


def _service_token() -> str:
    global _cached_service_token, _cached_service_token_until
    if not settings.ITHUTE_PUSH_ENABLED:
        raise IthutePushDisabled('!thute Push is disabled for Ithute Pay')
    if not settings.ITHUTE_PUSH_SERVICE_CLIENT_SECRET:
        raise IthutePushUnavailable('Ithute Pay push service credentials are not configured')

    now = time.monotonic()
    if _cached_service_token and now < _cached_service_token_until:
        return _cached_service_token

    with _token_lock:
        now = time.monotonic()
        if _cached_service_token and now < _cached_service_token_until:
            return _cached_service_token
        try:
            response = httpx.post(
                _auth_url('/v1/auth/service-token'),
                json={
                    'client_id': settings.ITHUTE_AUTH_AUDIENCE,
                    'client_secret': settings.ITHUTE_PUSH_SERVICE_CLIENT_SECRET,
                    'audience': 'ithute-push',
                    'scope': 'push.send',
                },
                timeout=settings.ITHUTE_PUSH_HTTP_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise IthutePushUnavailable('Unable to obtain !thute Push service token') from exc
        token = str(payload.get('access_token') or '') if isinstance(payload, dict) else ''
        expires_in = int(payload.get('expires_in') or 0) if isinstance(payload, dict) else 0
        if not token or expires_in <= 0:
            raise IthutePushUnavailable('!thute Auth returned an incomplete service token')
        _cached_service_token = token
        _cached_service_token_until = time.monotonic() + max(1, expires_in - 20)
        return token


def _user_request(method: str, path: str, *, access_token: str, json_body: dict[str, Any] | None = None) -> Any:
    if not settings.ITHUTE_PUSH_ENABLED:
        raise IthutePushDisabled('!thute Push is disabled for Ithute Pay')
    try:
        response = httpx.request(
            method,
            _push_url(path),
            headers={'Authorization': f'Bearer {access_token}'},
            json=json_body,
            timeout=settings.ITHUTE_PUSH_HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        if response.status_code == 204:
            return None
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise IthutePushUnavailable('!thute Push device service is unavailable') from exc


def register_device(access_token: str, payload: dict[str, Any]) -> dict[str, Any]:
    result = _user_request('POST', '/v1/devices', access_token=access_token, json_body=payload)
    return result if isinstance(result, dict) else {}


def list_devices(access_token: str) -> list[dict[str, Any]]:
    result = _user_request('GET', '/v1/devices', access_token=access_token)
    return result if isinstance(result, list) else []


def revoke_device(access_token: str, device_key: str) -> None:
    _user_request('DELETE', f"/v1/devices/{quote(device_key, safe='')}", access_token=access_token)


def send_notification(
    *,
    recipient_sub: str,
    title: str,
    body: str,
    route: str | None = None,
    sound: str | None = 'default',
    data: dict[str, Any] | None = None,
    ttl_seconds: int = 3600,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    token = _service_token()
    headers = {'Authorization': f'Bearer {token}'}
    if idempotency_key:
        headers['Idempotency-Key'] = idempotency_key[:128]
    try:
        response = httpx.post(
            _push_url('/v1/messages'),
            headers=headers,
            json={
                'recipient_sub': recipient_sub,
                'title': title,
                'body': body,
                'route': route,
                'sound': sound,
                'data': data or {},
                'ttl_seconds': ttl_seconds,
            },
            timeout=settings.ITHUTE_PUSH_HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise IthutePushUnavailable('Unable to queue !thute Push notification') from exc
    if not isinstance(payload, dict):
        raise IthutePushUnavailable('!thute Push returned an invalid response')
    return payload
