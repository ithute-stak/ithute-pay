from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.access_control import MerchantContext, merchant_context
from services.crypto_service import encrypt_local_secret
from core.security import generate_secret, sha256_text
from database.session import get_db
from database.models import Event, WebhookDelivery, WebhookEndpoint
from database.schemas.webhooks import EventOut, WebhookDeliveryOut, WebhookEndpointCreate, WebhookEndpointCreated, WebhookEndpointOut

router = APIRouter(prefix="/developer", tags=["Developer Tools"])


@router.get("/events", response_model=list[EventOut])
def list_events(db: Session = Depends(get_db), ctx: MerchantContext = Depends(merchant_context), limit: int = 50):
    return db.scalars(select(Event).where(Event.application_id == ctx.application.id)
                      .order_by(Event.created_at.desc()).limit(min(limit, 200))).all()


@router.get("/webhook-endpoints", response_model=list[WebhookEndpointOut])
def list_webhooks(db: Session = Depends(get_db), ctx: MerchantContext = Depends(merchant_context)):
    return db.scalars(select(WebhookEndpoint).where(WebhookEndpoint.application_id == ctx.application.id)
                      .order_by(WebhookEndpoint.created_at.desc())).all()


@router.post("/webhook-endpoints", response_model=WebhookEndpointCreated, status_code=201)
def create_webhook(payload: WebhookEndpointCreate, db: Session = Depends(get_db), ctx: MerchantContext = Depends(merchant_context)):
    secret = generate_secret("whsec_", 32)
    row = WebhookEndpoint(application_id=ctx.application.id, merchant_id=ctx.merchant.id, url=payload.url,
                          signing_secret_hash=sha256_text(secret), secret_ciphertext=encrypt_local_secret(secret),
                          event_types=payload.event_types, enabled=True)
    db.add(row); db.commit(); db.refresh(row)
    return WebhookEndpointCreated(id=row.id, url=row.url, event_types=row.event_types,
                                  enabled=row.enabled, signing_secret=secret)


@router.post("/webhook-endpoints/{webhook_id}/disable")
def disable_webhook(webhook_id: str, db: Session = Depends(get_db), ctx: MerchantContext = Depends(merchant_context)):
    row = db.get(WebhookEndpoint, webhook_id)
    if not row or row.application_id != ctx.application.id: raise HTTPException(status_code=404, detail="Webhook not found")
    row.enabled = False; db.add(row); db.commit(); return {"message": "Webhook disabled"}


@router.get("/webhook-deliveries", response_model=list[WebhookDeliveryOut])
def list_deliveries(db: Session = Depends(get_db), ctx: MerchantContext = Depends(merchant_context), limit: int = 50):
    endpoint_ids = select(WebhookEndpoint.id).where(WebhookEndpoint.application_id == ctx.application.id)
    return db.scalars(select(WebhookDelivery).where(WebhookDelivery.webhook_endpoint_id.in_(endpoint_ids))
                      .order_by(WebhookDelivery.created_at.desc()).limit(min(limit, 200))).all()


@router.post("/webhook-deliveries/{delivery_id}/replay")
def replay(delivery_id: str, db: Session = Depends(get_db), ctx: MerchantContext = Depends(merchant_context)):
    row = db.get(WebhookDelivery, delivery_id)
    if not row: raise HTTPException(status_code=404, detail="Delivery not found")
    endpoint = db.get(WebhookEndpoint, row.webhook_endpoint_id)
    if not endpoint or endpoint.application_id != ctx.application.id: raise HTTPException(status_code=404, detail="Delivery not found")
    row.status = "pending"; row.next_attempt_at = None; db.add(row); db.commit()
    try:
        from workers.tasks import deliver_webhook
        deliver_webhook.delay(row.id)
    except Exception:
        # The database record remains pending and can be delivered by the worker later.
        pass
    return {"message": "Webhook replay queued"}
