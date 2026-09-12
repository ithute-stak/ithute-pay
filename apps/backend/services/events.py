from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import Event, WebhookDelivery, WebhookEndpoint
from utils.helpers import public_id
from core.realtime_events import queue_gateway_event


def json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


def publish_event(db: Session, *, application_id: str, merchant_id: str,
                  event_type: str, data: dict[str, Any]) -> Event:
    event = Event(
        public_id=public_id("evt"),
        application_id=application_id,
        merchant_id=merchant_id,
        event_type=event_type,
        data_json=json_safe(data),
    )
    db.add(event)
    db.flush()
    endpoints = db.scalars(select(WebhookEndpoint).where(
        WebhookEndpoint.application_id == application_id,
        WebhookEndpoint.enabled.is_(True),
    )).all()
    for endpoint in endpoints:
        if endpoint.event_types and event_type not in endpoint.event_types:
            continue
        db.add(WebhookDelivery(event_id=event.id, webhook_endpoint_id=endpoint.id))
    db.flush()
    queue_gateway_event(
        db,
        event_type=event_type,
        data=event.data_json,
        merchant_id=merchant_id,
        application_id=application_id,
    )
    return event
