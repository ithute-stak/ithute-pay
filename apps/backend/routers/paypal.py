from __future__ import annotations

import secrets
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import CheckoutSession, PaymentIntent, PaymentLink, ProviderTransaction
from database.session import get_db
from integrations.base import ProviderResult
from services.gateway_configuration import active_gateway_provider_configuration
from services.payments import apply_provider_result, create_provider_transaction
from services.paypal import PayPalClient, PayPalError, PayPalSettings
from utils.helpers import public_id, utcnow

router = APIRouter(tags=["PayPal Checkout"])
Kind = Literal["checkout-sessions", "payment-links"]


def _paypal(db: Session):
    row = active_gateway_provider_configuration(db, "paypal")
    if not row:
        raise HTTPException(status_code=503, detail="PayPal is not available")
    config = PayPalSettings.from_row(row)
    return row, config, PayPalClient(config)


def _source(db: Session, kind: Kind, token: str):
    if kind == "checkout-sessions":
        row = db.scalar(select(CheckoutSession).where(CheckoutSession.token == token))
        if not row:
            raise HTTPException(status_code=404, detail="Checkout session not found")
        if row.status not in {"open", "processing"}:
            raise HTTPException(status_code=409, detail="Checkout session is not open")
        if row.expires_at:
            now = utcnow()
            if getattr(row.expires_at, "tzinfo", None) is None:
                now = now.replace(tzinfo=None)
            if row.expires_at < now:
                row.status = "expired"
                db.commit()
                raise HTTPException(status_code=410, detail="Checkout session expired")
        return row
    row = db.scalar(select(PaymentLink).where(PaymentLink.token == token, PaymentLink.status == "active"))
    if not row:
        raise HTTPException(status_code=404, detail="Payment link not found")
    return row


def _payment(db: Session, source, kind: Kind) -> PaymentIntent:
    if kind == "checkout-sessions" and source.payment_intent_id:
        existing = db.get(PaymentIntent, source.payment_intent_id)
        if existing:
            return existing
    payment = PaymentIntent(
        public_id=public_id("pi"),
        application_id=source.application_id,
        merchant_id=source.merchant_id,
        amount=source.amount,
        currency=source.currency,
        provider="paypal",
        payment_method="card_or_paypal",
        reference=source.reference,
        description=source.description,
        status="created",
        metadata_json=dict(source.metadata_json or {}),
    )
    db.add(payment)
    db.flush()
    if kind == "checkout-sessions":
        source.payment_intent_id = payment.id
        source.status = "processing"
        db.add(source)
    return payment


@router.get("/public/{kind}/{token}/paypal/config")
def paypal_public_config(kind: Kind, token: str, db: Session = Depends(get_db)):
    source = _source(db, kind, token)
    _, config, _ = _paypal(db)
    supported = source.currency.upper() in config.supported_currencies
    return {
        "available": supported,
        "mode": config.mode,
        "client_id": config.client_id if config.mode == "live" else "",
        "currency": source.currency.upper(),
        "card_enabled": supported and config.card_enabled,
        "paypal_enabled": supported,
        "sdk_url": "https://www.paypal.com/sdk/js",
    }


@router.post("/public/{kind}/{token}/paypal/orders", status_code=201)
async def paypal_create_order(kind: Kind, token: str, db: Session = Depends(get_db)):
    source = _source(db, kind, token)
    _, _, client = _paypal(db)
    payment = _payment(db, source, kind)
    metadata = dict(payment.metadata_json or {})
    previous = metadata.get("paypal_order_id")
    if previous and payment.status in {"created", "processing"}:
        return {"order_id": previous, "status": "CREATED"}
    request_id = f"{payment.public_id}-create"
    try:
        order = await client.create_order(
            amount=payment.amount,
            currency=payment.currency,
            reference=payment.reference,
            idempotency_key=request_id,
        )
    except PayPalError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    order_id = str(order.get("id") or "")
    if not order_id:
        raise HTTPException(status_code=502, detail="PayPal returned an invalid order")
    metadata.update({"paypal_order_id": order_id, "paypal_order_status": order.get("status")})
    payment.metadata_json = metadata
    payment.status = "processing"
    if not db.scalar(select(ProviderTransaction).where(
        ProviderTransaction.resource_type == "payment_intent",
        ProviderTransaction.resource_id == payment.id,
    )):
        create_provider_transaction(db, resource_type="payment_intent", resource=payment, direction="inbound", provider="paypal")
    db.add(payment)
    db.commit()
    return {"order_id": order_id, "status": order.get("status", "CREATED")}


@router.post("/public/{kind}/{token}/paypal/orders/{order_id}/capture")
async def paypal_capture_order(kind: Kind, token: str, order_id: str, db: Session = Depends(get_db)):
    source = _source(db, kind, token)
    _, _, client = _paypal(db)
    payment = _payment(db, source, kind)
    metadata = dict(payment.metadata_json or {})
    expected = str(metadata.get("paypal_order_id") or "")
    if not expected or not secrets.compare_digest(expected, order_id):
        raise HTTPException(status_code=409, detail="Order does not belong to this checkout")
    transaction = db.scalar(select(ProviderTransaction).where(
        ProviderTransaction.resource_type == "payment_intent",
        ProviderTransaction.resource_id == payment.id,
        ProviderTransaction.provider == "paypal",
    ).order_by(ProviderTransaction.created_at.desc()))
    if not transaction:
        raise HTTPException(status_code=409, detail="Payment transaction was not initialized")
    if payment.status == "succeeded":
        return {"payment": {"id": payment.public_id, "status": payment.status}}
    try:
        result = await client.capture_order(order_id, idempotency_key=f"{payment.public_id}-capture")
    except PayPalError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    status = str(result.get("status") or "").upper()
    captures = (((result.get("purchase_units") or [{}])[0].get("payments") or {}).get("captures") or [{}])
    capture_id = str(captures[0].get("id") or order_id)
    mapped = "succeeded" if status == "COMPLETED" else "processing"
    apply_provider_result(db, transaction=transaction, result=ProviderResult(
        status=mapped,
        response_code=status or "UNKNOWN",
        response_description="PayPal order capture",
        transaction_id=capture_id,
        raw=result,
    ))
    metadata["paypal_order_status"] = status
    payment.metadata_json = metadata
    if kind == "checkout-sessions":
        source.status = "completed" if mapped == "succeeded" else mapped
        db.add(source)
    elif mapped == "succeeded" and not source.reusable:
        source.status = "completed"
        db.add(source)
    db.add(payment)
    db.commit()
    return {"payment": {"id": payment.public_id, "status": payment.status}}


@router.post("/provider-callbacks/paypal")
async def paypal_webhook(request: Request, db: Session = Depends(get_db)):
    _, _, client = _paypal(db)
    try:
        event: dict[str, Any] = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook JSON") from exc
    headers = {key.lower(): value for key, value in request.headers.items()}
    try:
        verified = await client.verify_webhook(headers=headers, event=event)
    except PayPalError as exc:
        raise HTTPException(status_code=502, detail="Webhook verification unavailable") from exc
    if not verified:
        raise HTTPException(status_code=400, detail="Invalid PayPal webhook signature")
    return {"received": True, "event_id": event.get("id")}
