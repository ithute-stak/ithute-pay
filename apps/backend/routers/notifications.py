from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from core.access_control import get_current_active_user
from core.security import central_access_token_from_request
from database.config.config import settings
from database.models.user import User
from services.ithute_push import (
    IthutePushDisabled,
    IthutePushUnavailable,
    list_devices,
    register_device,
    revoke_device,
    send_notification,
)


router = APIRouter(prefix='/notifications', tags=['Notifications'])


class DeviceRegistration(BaseModel):
    device_key: str = Field(min_length=8, max_length=200)
    platform: Literal['android', 'ios', 'web']
    provider_endpoint: str = Field(min_length=8, max_length=8192)


class TestNotification(BaseModel):
    title: str = Field(default='Ithute Pay', min_length=1, max_length=160)
    body: str = Field(default='Central push is connected to your Ithute Pay account.', min_length=1, max_length=500)
    route: str | None = Field(default='/dashboard', max_length=500)
    sound: str | None = Field(default='default', max_length=64)
    data: dict[str, Any] = Field(default_factory=lambda: {'source': 'ithute-pay', 'kind': 'push-test'})


def _push_failure(exc: Exception) -> HTTPException:
    if isinstance(exc, IthutePushDisabled):
        return HTTPException(status_code=503, detail='!thute Push is not enabled for Ithute Pay')
    return HTTPException(status_code=503, detail='!thute Push is temporarily unavailable')


@router.get('/status')
def notification_status(user: User = Depends(get_current_active_user)):
    return {
        'enabled': settings.ITHUTE_PUSH_ENABLED,
        'central_auth_linked': bool(user.auth_user_id),
        'client_id': settings.ITHUTE_AUTH_AUDIENCE,
        'push_url': settings.ITHUTE_PUSH_URL if settings.ITHUTE_PUSH_ENABLED else None,
    }


@router.post('/devices')
def add_device(
    payload: DeviceRegistration,
    request: Request,
    _: User = Depends(get_current_active_user),
):
    token = central_access_token_from_request(request)
    try:
        return register_device(token, payload.model_dump(mode='json'))
    except (IthutePushDisabled, IthutePushUnavailable) as exc:
        raise _push_failure(exc) from exc


@router.get('/devices')
def devices(
    request: Request,
    _: User = Depends(get_current_active_user),
):
    token = central_access_token_from_request(request)
    try:
        return {'items': list_devices(token)}
    except (IthutePushDisabled, IthutePushUnavailable) as exc:
        raise _push_failure(exc) from exc


@router.delete('/devices/{device_key}', status_code=204)
def remove_device(
    device_key: str,
    request: Request,
    _: User = Depends(get_current_active_user),
):
    token = central_access_token_from_request(request)
    try:
        revoke_device(token, device_key)
    except (IthutePushDisabled, IthutePushUnavailable) as exc:
        raise _push_failure(exc) from exc


@router.post('/test', status_code=202)
def test_notification(
    payload: TestNotification,
    user: User = Depends(get_current_active_user),
):
    if not user.auth_user_id:
        raise HTTPException(status_code=409, detail='Link this Ithute Pay user to !thute Auth before sending push notifications')
    try:
        return send_notification(
            recipient_sub=user.auth_user_id,
            title=payload.title,
            body=payload.body,
            route=payload.route,
            sound=payload.sound,
            data=payload.data,
            idempotency_key=f'ithute-pay-push-test:{user.id}:{uuid4().hex}',
        )
    except (IthutePushDisabled, IthutePushUnavailable) as exc:
        raise _push_failure(exc) from exc
