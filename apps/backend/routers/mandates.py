from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.access_control import MerchantContext, idempotency_key, merchant_context
from database.session import get_db
from database.models import Mandate, MandateCharge
from database.schemas.mandates import MandateChargeCreate, MandateChargeOut, MandateCreate, MandateOut
from integrations.mpesa.contracts import require_provider_capability
from integrations.registry import get_provider
from services.idempotency import get_existing, save_record
from services.mandates import cancel_mandate, charge_mandate, create_provider_mandate, refresh_mandate
from utils.helpers import json_hash, public_id

router = APIRouter(prefix="/mandates", tags=["Direct Debit Mandates"])


def owned(db: Session, public_id_value: str, ctx: MerchantContext) -> Mandate:
    row = db.scalar(select(Mandate).where(Mandate.public_id == public_id_value, Mandate.application_id == ctx.application.id))
    if not row: raise HTTPException(status_code=404, detail="Mandate not found")
    return row


def _preflight_direct_debit(db: Session, ctx: MerchantContext, provider_name: str) -> None:
    provider = get_provider(provider_name, db=db, application_id=ctx.application.id)
    require_provider_capability(provider, "direct_debit")


@router.post("", response_model=MandateOut, status_code=201)
async def create_mandate(payload: MandateCreate, db: Session = Depends(get_db), ctx: MerchantContext = Depends(merchant_context),
                         key: str = Depends(idempotency_key)):
    h = json_hash(payload.model_dump())
    existing = get_existing(db, application_id=ctx.application.id, key=key, operation="mandate.create", request_hash=h)
    if existing and existing.resource_id: return db.get(Mandate, existing.resource_id)
    _preflight_direct_debit(db, ctx, payload.provider)
    row = Mandate(public_id=public_id("mand"), application_id=ctx.application.id, merchant_id=ctx.merchant.id,
                  provider=payload.provider, customer_phone=payload.customer_phone,
                  third_party_reference=payload.reference, frequency=payload.frequency,
                  first_payment_date=payload.first_payment_date.isoformat() if payload.first_payment_date else None,
                  payment_day_from=payload.payment_day_from, payment_day_to=payload.payment_day_to,
                  expiry_date=payload.expiry_date.isoformat() if payload.expiry_date else None,
                  metadata_json=payload.metadata)
    db.add(row); db.flush()
    save_record(db, application_id=ctx.application.id, key=key, operation="mandate.create", request_hash=h,
                resource_type="mandate", resource_id=row.id, response_json={"id": row.public_id})
    db.commit(); db.refresh(row)
    return await create_provider_mandate(db, row, payload.agreed_terms)


@router.get("", response_model=list[MandateOut])
def list_mandates(db: Session = Depends(get_db), ctx: MerchantContext = Depends(merchant_context), limit: int = 50):
    return db.scalars(select(Mandate).where(Mandate.application_id == ctx.application.id)
                      .order_by(Mandate.created_at.desc()).limit(min(limit, 200))).all()


@router.get("/{mandate_id}", response_model=MandateOut)
def get_mandate(mandate_id: str, db: Session = Depends(get_db), ctx: MerchantContext = Depends(merchant_context)):
    return owned(db, mandate_id, ctx)


@router.post("/{mandate_id}/refresh")
async def refresh(mandate_id: str, db: Session = Depends(get_db), ctx: MerchantContext = Depends(merchant_context)):
    mandate = owned(db, mandate_id, ctx)
    _preflight_direct_debit(db, ctx, mandate.provider)
    return await refresh_mandate(db, mandate)


@router.post("/{mandate_id}/charges", response_model=MandateChargeOut, status_code=201)
async def create_charge(mandate_id: str, payload: MandateChargeCreate, db: Session = Depends(get_db),
                        ctx: MerchantContext = Depends(merchant_context), key: str = Depends(idempotency_key)):
    mandate = owned(db, mandate_id, ctx)
    h = json_hash(payload.model_dump())
    existing = get_existing(db, application_id=ctx.application.id, key=key, operation="mandate.charge", request_hash=h)
    if existing and existing.resource_id: return db.get(MandateCharge, existing.resource_id)
    _preflight_direct_debit(db, ctx, mandate.provider)
    charge = MandateCharge(public_id=public_id("mc"), mandate_id=mandate.id, application_id=ctx.application.id,
                           merchant_id=ctx.merchant.id, amount=payload.amount, currency=payload.currency.upper(),
                           reference=payload.reference)
    db.add(charge); db.flush()
    save_record(db, application_id=ctx.application.id, key=key, operation="mandate.charge", request_hash=h,
                resource_type="mandate_charge", resource_id=charge.id, response_json={"id": charge.public_id})
    db.commit(); db.refresh(charge)
    return await charge_mandate(db, mandate, charge, check_balance_first=payload.check_balance_first)


@router.get("/{mandate_id}/charges", response_model=list[MandateChargeOut])
def list_mandate_charges(mandate_id: str, db: Session = Depends(get_db), ctx: MerchantContext = Depends(merchant_context), limit: int = 50):
    mandate = owned(db, mandate_id, ctx)
    return db.scalars(select(MandateCharge).where(MandateCharge.mandate_id == mandate.id, MandateCharge.application_id == ctx.application.id)
                      .order_by(MandateCharge.created_at.desc()).limit(min(limit, 200))).all()


@router.post("/{mandate_id}/cancel", response_model=MandateOut)
async def cancel(mandate_id: str, db: Session = Depends(get_db), ctx: MerchantContext = Depends(merchant_context)):
    mandate = owned(db, mandate_id, ctx)
    _preflight_direct_debit(db, ctx, mandate.provider)
    return await cancel_mandate(db, mandate)
