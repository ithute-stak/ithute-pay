from __future__ import annotations

from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session

from core.websocket_manager import manager


_REALTIME_QUEUE_KEY = 'paybridge_realtime_events'


async def publish_gateway_event(
    *,
    event_type: str,
    data: dict[str, Any],
    merchant_id: str | None = None,
    application_id: str | None = None,
) -> None:
    payload = {
        'type': 'GATEWAY_EVENT',
        'event_type': event_type,
        'data': data,
    }

    await manager.send_to_channel('platform', payload)
    if merchant_id:
        await manager.send_to_channel(f'merchant-{merchant_id}', payload)
    if application_id:
        await manager.send_to_channel(f'application-{application_id}', payload)


def schedule_gateway_event(
    *,
    event_type: str,
    data: dict[str, Any],
    merchant_id: str | None = None,
    application_id: str | None = None,
) -> None:
    manager.schedule(
        publish_gateway_event(
            event_type=event_type,
            data=data,
            merchant_id=merchant_id,
            application_id=application_id,
        )
    )


def queue_gateway_event(
    db: Session,
    *,
    event_type: str,
    data: dict[str, Any],
    merchant_id: str | None = None,
    application_id: str | None = None,
) -> None:
    """Queue realtime delivery until the surrounding DB transaction commits."""
    queue = db.info.setdefault(_REALTIME_QUEUE_KEY, [])
    queue.append(
        {
            'event_type': event_type,
            'data': data,
            'merchant_id': merchant_id,
            'application_id': application_id,
        }
    )


@event.listens_for(Session, 'after_commit')
def _publish_after_commit(session: Session) -> None:
    queued = session.info.pop(_REALTIME_QUEUE_KEY, [])
    for item in queued:
        schedule_gateway_event(**item)


@event.listens_for(Session, 'after_rollback')
def _discard_after_rollback(session: Session) -> None:
    session.info.pop(_REALTIME_QUEUE_KEY, None)
