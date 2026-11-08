"""Merchant-scoped, non-posting pass-through fee quote endpoint.

The merchant is ALWAYS derived from the API key, never from the request body.
No financial records, provider requests or transfers are created here.
"""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.access_control import MerchantContext, merchant_context
from database.models import MerchantCommercialAgreement, TenantMerchantContract
from database.session import get_db
from services.mpesa_pass_through_quotes import quote_from_agreement

router = APIRouter(prefix="/merchant/mpesa-pass-through", tags=["M-Pesa Pass-Through Preview"])


class PassThroughQuoteRequest(BaseModel):
    direction: str = Field(pattern="^(incoming|outgoing)$")
    amount: Decimal = Field(gt=0, decimal_places=2, max_digits=18)
    currency: str = Field(default="LSL", pattern="^LSL$")


@router.post("/quote")
def preview_pass_through_quote(
    payload: PassThroughQuoteRequest,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_context),
) -> dict:
    contract = db.scalar(select(TenantMerchantContract).where(
        TenantMerchantContract.tenant_merchant_id == ctx.merchant.id,
    ))
    if not contract or contract.status != "approved" or contract.kyc_status != "verified":
        raise HTTPException(status_code=403, detail="Approved KYC-verified tenant required")
    if contract.custody_mode != "own_shortcode":
        raise HTTPException(status_code=409, detail="Shared merchant custody is not enabled")
    agreement = db.scalar(select(MerchantCommercialAgreement).where(
        MerchantCommercialAgreement.merchant_id == ctx.merchant.id,
        MerchantCommercialAgreement.status == "approved",
        MerchantCommercialAgreement.currency == payload.currency,
    ).order_by(MerchantCommercialAgreement.version.desc()))
    if agreement is None:
        # Fail closed; the 1% tariff is a default configuration, never an
        # implicit authorization for a tenant without an approved agreement.
        raise HTTPException(status_code=409, detail="Approved tenant pricing agreement required")
    try:
        quoted = quote_from_agreement(ctx.merchant.id, payload.direction, payload.amount, agreement)
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return quoted.payload()
