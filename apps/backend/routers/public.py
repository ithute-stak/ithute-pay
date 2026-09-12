from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.session import get_db
from database.models import CheckoutSession, PaymentIntent, PaymentLink
from database.schemas.checkout import PublicCheckoutPay
from database.schemas.gateway import RoutedCollectionCreate
from services.payment_methods import direct_collection_method, payment_method_catalog
from services.payments import confirm_payment
from utils.helpers import public_id, utcnow

router = APIRouter(prefix="/public", tags=["Public Checkout"])


def _expired(value) -> bool:
    if value is None:
        return False
    now = utcnow()
    # SQLite may return timezone-naive DateTime values in tests/dev while
    # PostgreSQL preserves timezone-aware timestamps. Compare like with like.
    if getattr(value, "tzinfo", None) is None:
        now = now.replace(tzinfo=None)
    return value < now


def checkout_payload(row: CheckoutSession) -> dict:
    return {
        "token": row.token,
        "amount": str(row.amount),
        "currency": row.currency,
        "reference": row.reference,
        "description": row.description,
        "status": row.status,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "payment_intent_id": row.payment_intent_id,
        "success_url": row.success_url,
        "cancel_url": row.cancel_url,
    }


@router.get("/payment-methods")
def public_payment_methods(
    currency: str = Query(default="LSL", min_length=3, max_length=3),
    db: Session = Depends(get_db),
):
    """Return only safe, active collection rails for the requested currency.

    Provider credentials, internal URLs and account identifiers are deliberately
    excluded. Consumers use the field descriptors to build a provider-specific
    form without hard-coding the gateway configuration.
    """
    return payment_method_catalog(db, currency)


@router.get("/checkout-sessions/{token}")
def public_checkout(token: str, db: Session = Depends(get_db)):
    row = db.scalar(select(CheckoutSession).where(CheckoutSession.token == token))
    if not row: raise HTTPException(status_code=404, detail="Checkout session not found")
    if _expired(row.expires_at):
        row.status = "expired"; db.commit()
    return checkout_payload(row)


@router.post("/checkout-sessions/{token}/pay")
async def public_checkout_pay(token: str, payload: PublicCheckoutPay, db: Session = Depends(get_db)):
    row = db.scalar(select(CheckoutSession).where(CheckoutSession.token == token))
    if not row: raise HTTPException(status_code=404, detail="Checkout session not found")
    if row.status not in {"open", "processing"}: raise HTTPException(status_code=409, detail="Checkout session is not open")
    if _expired(row.expires_at):
        row.status = "expired"; db.commit(); raise HTTPException(status_code=410, detail="Checkout session expired")
    method = direct_collection_method(db, currency=row.currency, provider=payload.provider)
    if not method:
        raise HTTPException(
            status_code=422,
            detail="The selected payment provider is not available for this currency",
        )
    if row.payment_intent_id:
        payment = db.get(PaymentIntent, row.payment_intent_id)
    else:
        payment = PaymentIntent(
            public_id=public_id("pi"), application_id=row.application_id, merchant_id=row.merchant_id,
            amount=row.amount, currency=row.currency, provider=method["provider"],
            payment_method=method["payment_method"], customer_phone=payload.phone,
            reference=row.reference, description=row.description,
            status="created", metadata_json=row.metadata_json,
        )
        db.add(payment); db.flush(); row.payment_intent_id = payment.id; row.status = "processing"; db.add(row); db.commit()
    payment = await confirm_payment(db, payment)
    row.status = "completed" if payment.status == "succeeded" else payment.status
    db.add(row); db.commit()
    return {"checkout": checkout_payload(row), "payment": {"id": payment.public_id, "status": payment.status}}


@router.get("/payment-links/{token}")
def public_payment_link(token: str, db: Session = Depends(get_db)):
    row = db.scalar(select(PaymentLink).where(PaymentLink.token == token, PaymentLink.status == "active"))
    if not row: raise HTTPException(status_code=404, detail="Payment link not found")
    return {"token": row.token, "amount": str(row.amount), "currency": row.currency,
            "reference": row.reference, "description": row.description, "reusable": row.reusable}

@router.post("/payment-links/{token}/pay")
async def public_payment_link_pay(token: str, payload: PublicCheckoutPay, db: Session = Depends(get_db)):
    row = db.scalar(select(PaymentLink).where(PaymentLink.token == token, PaymentLink.status == "active"))
    if not row:
        raise HTTPException(status_code=404, detail="Payment link not found")
    method = direct_collection_method(db, currency=row.currency, provider=payload.provider)
    if not method:
        raise HTTPException(
            status_code=422,
            detail="The selected payment provider is not available for this currency",
        )
    payment = PaymentIntent(
        public_id=public_id("pi"), application_id=row.application_id, merchant_id=row.merchant_id,
        amount=row.amount, currency=row.currency, provider=method["provider"],
        payment_method=method["payment_method"], customer_phone=payload.phone,
        reference=row.reference, description=row.description,
        status="created", metadata_json=row.metadata_json,
    )
    db.add(payment); db.commit(); db.refresh(payment)
    payment = await confirm_payment(db, payment)
    if payment.status == "succeeded" and not row.reusable:
        row.status = "completed"; db.add(row); db.commit()
    return {"payment": {"id": payment.public_id, "status": payment.status}}


def _routed_payment_payload(db: Session, payment: PaymentIntent) -> dict:
    from database.models import Merchant, SettlementInstruction, ProviderTransaction
    merchant = db.get(Merchant, payment.merchant_id)
    tx = db.scalar(select(ProviderTransaction).where(
        ProviderTransaction.resource_type == "payment_intent",
        ProviderTransaction.resource_id == payment.id,
    ).order_by(ProviderTransaction.created_at.desc()))
    settlement = None
    if tx:
        settlement = db.scalar(select(SettlementInstruction).where(SettlementInstruction.source_transaction_id == tx.id))
    metadata = payment.metadata_json or {}
    return {
        "payment_id": payment.public_id,
        "status": payment.status,
        "merchant": {
            "id": payment.merchant_id,
            "name": merchant.name if merchant else None,
            "merchant_number": metadata.get("merchant_number"),
        },
        "customer_reference": metadata.get("customer_reference"),
        "reference": metadata.get("client_reference") or payment.reference,
        "reason": metadata.get("reason") or payment.description,
        "amount": str(payment.amount),
        "currency": payment.currency,
        "provider": payment.provider,
        "settlement": ({
            "id": settlement.public_id,
            "gross_amount": str(settlement.gross_amount),
            "fee_amount": str(settlement.fee_amount),
            "net_amount": str(settlement.net_amount),
            "currency": settlement.currency,
            "status": settlement.status,
        } if settlement else None),
    }


def _resolve_routed_merchant(db: Session, merchant_number: str):
    from database.models import Merchant, MerchantGatewayProfile, MerchantRoutingKey
    value = merchant_number.strip()
    profile = db.scalar(select(MerchantGatewayProfile).where(
        MerchantGatewayProfile.merchant_number == value,
        MerchantGatewayProfile.enabled.is_(True),
    ))
    if not profile:
        keys = db.scalars(select(MerchantRoutingKey).where(
            MerchantRoutingKey.key_value == value,
            MerchantRoutingKey.enabled.is_(True),
        ).order_by(MerchantRoutingKey.created_at.desc())).all()
        merchant_ids = {key.merchant_id for key in keys}
        if len(merchant_ids) > 1:
            raise HTTPException(status_code=409, detail="Merchant route is ambiguous; contact gateway support")
        merchant_id = next(iter(merchant_ids), None)
        profile = db.scalar(select(MerchantGatewayProfile).where(
            MerchantGatewayProfile.merchant_id == merchant_id,
            MerchantGatewayProfile.enabled.is_(True),
        )) if merchant_id else None
    if not profile:
        raise HTTPException(status_code=404, detail="Merchant number was not found or is not enabled")
    merchant = db.get(Merchant, profile.merchant_id)
    if not merchant or merchant.status != "active":
        raise HTTPException(status_code=409, detail="Merchant is not active")
    return merchant, profile


def _routed_application(db: Session, profile):
    from database.models import Application
    if profile.default_application_id:
        app = db.get(Application, profile.default_application_id)
        if app and app.status == "active":
            return app
    return db.scalar(select(Application).where(
        Application.merchant_id == profile.merchant_id,
        Application.status == "active",
    ).order_by(Application.created_at.asc()))


@router.post("/routed-collections", status_code=201)
async def create_routed_collection(payload: RoutedCollectionCreate, db: Session = Depends(get_db)):
    """Public collection entry point for schools, lenders, insurers and similar clients.

    The gateway owns the M-Pesa merchant credentials. `merchant_number` only routes
    the payment to the correct client ledger/settlement account. `customer_reference`
    is sector-neutral: student number, loan number, policy number, invoice number, etc.
    """
    from database.models import PaymentIntent
    from utils.helpers import public_id

    merchant, profile = _resolve_routed_merchant(db, payload.merchant_number)
    app = _routed_application(db, profile)
    if not app:
        raise HTTPException(status_code=409, detail="Merchant does not have an active gateway application")

    # When callers provide an idempotency key, retries return the original payment
    # instead of creating a second M-Pesa PIN prompt/charge.
    if payload.idempotency_key:
        existing_rows = db.scalars(select(PaymentIntent).where(
            PaymentIntent.merchant_id == merchant.id,
            PaymentIntent.application_id == app.id,
        ).order_by(PaymentIntent.created_at.desc()).limit(500)).all()
        for existing in existing_rows:
            if (existing.metadata_json or {}).get("idempotency_key") == payload.idempotency_key:
                return _routed_payment_payload(db, existing)

    metadata = dict(payload.metadata)
    metadata.update({
        "merchant_number": payload.merchant_number.strip(),
        "customer_reference": payload.customer_reference.strip(),
        "client_reference": payload.reference.strip(),
        "reason": payload.reason.strip(),
        "sector": profile.sector,
    })
    if payload.idempotency_key:
        metadata["idempotency_key"] = payload.idempotency_key

    payment = PaymentIntent(
        public_id=public_id("pi"), application_id=app.id, merchant_id=merchant.id,
        amount=payload.amount, currency=payload.currency.upper(), provider="mpesa", payment_method="mobile_money",
        customer_phone=payload.phone, reference=payload.reference.strip(), description=payload.reason.strip(),
        status="created", metadata_json=metadata,
    )
    db.add(payment); db.commit(); db.refresh(payment)
    payment = await confirm_payment(db, payment)
    return _routed_payment_payload(db, payment)


@router.get("/routed-collections/{payment_public_id}")
def routed_collection_status(payment_public_id: str, db: Session = Depends(get_db)):
    payment = db.scalar(select(PaymentIntent).where(PaymentIntent.public_id == payment_public_id))
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    metadata = payment.metadata_json or {}
    if not metadata.get("merchant_number") or not metadata.get("customer_reference"):
        raise HTTPException(status_code=404, detail="Routed payment not found")
    return _routed_payment_payload(db, payment)
