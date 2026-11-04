"""Tenant-owned provider account onboarding; no payment routing changes.

Merchant APIs can submit and inspect their own shortcode requests. Only a
platform administrator can verify/activate one after external provider checks.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.access_control import MerchantContext, merchant_context
from routers.merchant_network_admin import _network_admin
from database.models import (
    MerchantCommercialAgreement, TenantMerchantContract, TenantProviderAccount, User,
)
from database.session import get_db
from services.audit import write_audit

tenant_router = APIRouter(prefix="/merchant/tenancy", tags=["Merchant Tenancy"])
admin_router = APIRouter(prefix="/admin/tenancy", tags=["Tenant Administration"])


class ShortcodeRequest(BaseModel):
    provider: str = Field(default="mpesa", pattern="^mpesa$")
    environment: str = Field(default="production", pattern="^(production|sandbox)$")
    shortcode: str = Field(min_length=4, max_length=12, pattern=r"^[0-9]{4,12}$")


class ShortcodeVerification(BaseModel):
    evidence_reference: str = Field(min_length=8, max_length=180)
    approve: bool


def _shortcode_payload(row: TenantProviderAccount) -> dict:
    return {
        "id": row.id, "provider": row.provider, "environment": row.environment,
        "shortcode": row.shortcode, "ownership_status": row.ownership_status,
        "enabled": row.enabled,
        "verified_at": row.verified_at.isoformat() if row.verified_at else None,
    }


@tenant_router.get("/account")
def tenant_account(
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_context),
):
    contract = db.scalar(select(TenantMerchantContract).where(
        TenantMerchantContract.tenant_merchant_id == ctx.merchant.id,
    ))
    return {
        "merchant_id": ctx.merchant.id,
        "contract_status": contract.status if contract else "not_onboarded",
        "kyc_status": contract.kyc_status if contract else "not_onboarded",
        "custody_mode": contract.custody_mode if contract else None,
        "shared_custody_enabled": False,  # Not available through this API.
    }


@tenant_router.get("/shortcodes")
def tenant_shortcodes(
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_context),
):
    rows = db.scalars(select(TenantProviderAccount).where(
        TenantProviderAccount.merchant_id == ctx.merchant.id,
    ).order_by(TenantProviderAccount.created_at.desc())).all()
    return [_shortcode_payload(row) for row in rows]


@tenant_router.post("/shortcodes", status_code=201)
def request_shortcode(
    payload: ShortcodeRequest,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_context),
):
    contract = db.scalar(select(TenantMerchantContract).where(
        TenantMerchantContract.tenant_merchant_id == ctx.merchant.id,
        TenantMerchantContract.status.in_(("pending", "approved")),
        TenantMerchantContract.custody_mode == "own_shortcode",
    ))
    if contract is None:
        raise HTTPException(status_code=403, detail="Own-shortcode tenant onboarding is required")
    row = TenantProviderAccount(
        merchant_id=ctx.merchant.id, provider=payload.provider,
        environment=payload.environment, shortcode=payload.shortcode,
        ownership_status="pending", enabled=False,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        # Do not disclose the identity of the shortcode's existing owner.
        raise HTTPException(status_code=409, detail="Shortcode is already registered") from None
    write_audit(
        db, actor_type="api_key", actor_id=ctx.api_key.id,
        action="tenant_shortcode.requested", resource_type="tenant_provider_account",
        resource_id=row.id, merchant_id=ctx.merchant.id,
        metadata={"provider": row.provider, "environment": row.environment},
    )
    db.commit()
    db.refresh(row)
    return _shortcode_payload(row)


@tenant_router.get("/agreement")
def tenant_agreement(
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_context),
):
    row = db.scalar(select(MerchantCommercialAgreement).where(
        MerchantCommercialAgreement.merchant_id == ctx.merchant.id,
        MerchantCommercialAgreement.status == "approved",
    ).order_by(MerchantCommercialAgreement.version.desc()))
    if row is None:
        raise HTTPException(status_code=404, detail="No approved commercial agreement")
    return {
        "version": row.version, "currency": row.currency,
        "inbound_fixed_fee": str(row.inbound_fixed_fee),
        "inbound_percentage_fee": str(row.inbound_percentage_fee),
        "outbound_fixed_fee": str(row.outbound_fixed_fee),
        "outbound_percentage_fee": str(row.outbound_percentage_fee),
        "provider_cost_payer": row.provider_cost_payer,
        "effective_at": row.effective_at.isoformat() if row.effective_at else None,
    }


@admin_router.get("/shortcode-requests")
def pending_shortcodes(
    db: Session = Depends(get_db), _: User = Depends(_network_admin),
):
    rows = db.scalars(select(TenantProviderAccount).where(
        TenantProviderAccount.ownership_status == "pending",
    ).order_by(TenantProviderAccount.created_at)).all()
    return [{"merchant_id": row.merchant_id, **_shortcode_payload(row)} for row in rows]


@admin_router.post("/shortcodes/{account_id}/verify")
def verify_shortcode(
    account_id: str, payload: ShortcodeVerification,
    db: Session = Depends(get_db), user: User = Depends(_network_admin),
):
    row = db.scalar(select(TenantProviderAccount).where(
        TenantProviderAccount.id == account_id,
    ).with_for_update())
    if row is None:
        raise HTTPException(status_code=404, detail="Shortcode request not found")
    if row.ownership_status != "pending":
        raise HTTPException(status_code=409, detail="Request already reviewed")
    contract = db.scalar(select(TenantMerchantContract).where(
        TenantMerchantContract.tenant_merchant_id == row.merchant_id,
    ))
    if not contract or contract.custody_mode != "own_shortcode":
        raise HTTPException(status_code=409, detail="Tenant does not hold an own-shortcode contract")
    if payload.approve and not (
        contract.status == "approved" and contract.kyc_status == "verified"
    ):
        raise HTTPException(status_code=409, detail="Tenant must be approved and KYC-verified")
    row.ownership_status = "verified" if payload.approve else "rejected"
    row.verified_at = datetime.now(timezone.utc) if payload.approve else None
    row.verified_by = str(user.id) if payload.approve else None
    # Verification does NOT enable provider routing. Activation is a separate
    # future, provider-certified step requiring its own controls.
    row.enabled = False
    write_audit(
        db, actor_type="user", actor_id=user.id,
        action="tenant_shortcode.verified" if payload.approve else "tenant_shortcode.rejected",
        resource_type="tenant_provider_account", resource_id=row.id,
        merchant_id=row.merchant_id,
        metadata={
            "provider": row.provider, "environment": row.environment,
            "evidence_reference": payload.evidence_reference,
        },
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"merchant_id": row.merchant_id, **_shortcode_payload(row)}
