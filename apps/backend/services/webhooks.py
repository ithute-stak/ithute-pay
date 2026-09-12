from __future__ import annotations

import json
import time
from datetime import timedelta
import httpx
from sqlalchemy.orm import Session

from database.config.config import settings
from services.crypto_service import decrypt_local_secret
from core.security import webhook_signature
from database.session import SessionLocal
from database.models import Event, WebhookDelivery, WebhookEndpoint
from utils.helpers import utcnow

RETRY_DELAYS = [0, 30, 120, 600, 1800, 7200, 21600, 43200, 86400]


def event_payload(event: Event) -> dict:
    return {
        "id": event.public_id,
        "type": event.event_type,
        "created_at": event.created_at.isoformat(),
        "data": event.data_json,
    }


def deliver_once(db: Session, delivery: WebhookDelivery) -> WebhookDelivery:
    event = db.get(Event, delivery.event_id)
    endpoint = db.get(WebhookEndpoint, delivery.webhook_endpoint_id)
    if not event or not endpoint or not endpoint.enabled:
        delivery.status = "cancelled"
        db.commit()
        return delivery
    payload = json.dumps(event_payload(event), separators=(",", ":"), sort_keys=True).encode()
    timestamp = int(time.time())
    secret = decrypt_local_secret(endpoint.secret_ciphertext)
    signature = webhook_signature(secret, timestamp, payload)
    delivery.attempt_count += 1
    try:
        with httpx.Client(timeout=12) as client:
            response = client.post(endpoint.url, content=payload, headers={
                "Content-Type": "application/json",
                "User-Agent": "Ithute Pay Bridge-Webhooks/1.0",
                "X-IPB-Signature": signature,
                "X-IPB-Event": event.event_type,
                "X-IPB-Event-ID": event.public_id,
            })
        delivery.last_status_code = response.status_code
        if 200 <= response.status_code < 300:
            delivery.status = "delivered"
            delivery.last_error = None
            delivery.next_attempt_at = None
        else:
            delivery.status = "retrying"
            delivery.last_error = response.text[:1000]
    except Exception as exc:
        delivery.status = "retrying"
        delivery.last_error = str(exc)[:1000]
    if delivery.status == "retrying":
        if delivery.attempt_count >= settings.WEBHOOK_MAX_ATTEMPTS:
            delivery.status = "failed"
            delivery.next_attempt_at = None
        else:
            delay = RETRY_DELAYS[min(delivery.attempt_count, len(RETRY_DELAYS) - 1)]
            delivery.next_attempt_at = utcnow() + timedelta(seconds=delay)
    db.add(delivery)
    db.commit()
    db.refresh(delivery)
    return delivery


def deliver_by_id(delivery_id: str) -> None:
    with SessionLocal() as db:
        row = db.get(WebhookDelivery, delivery_id)
        if row:
            deliver_once(db, row)
