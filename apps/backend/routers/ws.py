from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from core.websocket_manager import manager
from database.models.user import User
from database.session import get_db
from utils.decode_encode_token import decode_token


WS_SESSION_COOKIE = 'ipb_ws_session'
router = APIRouter(prefix='/ws', tags=['WebSockets'])


def _websocket_token(websocket: WebSocket) -> tuple[str | None, str | None]:
    requested_protocols = list(websocket.scope.get('subprotocols') or [])
    if not requested_protocols:
        protocol_header = websocket.headers.get('sec-websocket-protocol', '')
        requested_protocols = [item.strip() for item in protocol_header.split(',') if item.strip()]

    protocol_token = next(
        (
            item.removeprefix('paybridge.jwt.')
            for item in requested_protocols
            if item.startswith('paybridge.jwt.')
        ),
        None,
    )
    accepted_protocol = 'paybridge.v1' if 'paybridge.v1' in requested_protocols else None
    return (
        websocket.cookies.get(WS_SESSION_COOKIE)
        or protocol_token
        or websocket.query_params.get('token'),
        accepted_protocol,
    )


def _client_id(websocket: WebSocket, user_id: str) -> str:
    supplied = (websocket.query_params.get('client_id') or '').strip()
    if supplied and len(supplied) <= 128:
        return supplied
    return f'client-{user_id}'


@router.websocket('')
async def websocket_auth_endpoint(
    websocket: WebSocket,
    db: Session = Depends(get_db),
) -> None:
    token, accepted_protocol = _websocket_token(websocket)
    if not token:
        await websocket.close(code=1008, reason='Missing access token')
        return

    try:
        payload = decode_token(token)
    except HTTPException:
        await websocket.close(code=1008, reason='Invalid access token')
        return

    if payload.get('token_type') not in {'access', 'websocket'}:
        await websocket.close(code=1008, reason='WebSocket authentication required')
        return

    user_id = str(payload.get('user_id') or payload.get('sub') or '')
    user = db.get(User, user_id) if user_id else None
    if not user or not user.is_active:
        await websocket.close(code=1008, reason='Account unavailable')
        return

    channels = {
        'platform',
        f'user-{user.id}',
        f'role-{user.role}',
    }
    client_id = _client_id(websocket, str(user.id))

    await websocket.accept(subprotocol=accepted_protocol)
    await manager.register_client(str(user.id), client_id, websocket)
    for channel in channels:
        manager.subscribe(channel, websocket)

    try:
        await websocket.send_json(
            {
                'type': 'SOCKET_CONNECTED',
                'user_id': str(user.id),
                'role': user.role,
                'channels': sorted(channels),
            }
        )
        while True:
            message = await websocket.receive_text()
            if message.strip().lower() == 'ping':
                await websocket.send_text('pong')
                continue
            try:
                event = json.loads(message)
            except json.JSONDecodeError:
                continue
            if event.get('type') == 'PING':
                await websocket.send_json({'type': 'PONG'})
    except WebSocketDisconnect:
        pass
    finally:
        manager.unregister_client(str(user.id), client_id, websocket)
        manager.disconnect_all(websocket)
