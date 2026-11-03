"""Cookie-authenticated, strictly tenant-scoped merchant portal.

No browser POS API keys and no live payment dispatches. Membership grants
are platform-administrator-only until delegated tenant roles are reviewed.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.access_control import get_current_active_user
from database.models import (
    Merchant, MerchantCommercialAgreement, TenantMerchantContract,
    TenantProviderAccount, TenantUserMembership, User,
)
from database.session import get_db
from routers.merchant_network_admin import _network_admin
from services.audit import write_audit

router = APIRouter(prefix="/tenant-portal", tags=["Tenant Merchant Portal"])
admin_router = APIRouter(prefix="/admin/tenant-access", tags=["Tenant User Access"])


class TenantMembershipGrant(BaseModel):
    user_id: str = Field(min_length=36, max_length=36)
    merchant_id: str = Field(min_length=36, max_length=36)
    role: str = Field(default="viewer", pattern="^(owner|manager|finance|developer|viewer)$")


def _allowed_tenant(db: Session, user: User, merchant_id: str) -> Merchant:
    membership = db.scalar(select(TenantUserMembership).where(
        TenantUserMembership.user_id == user.id,
        TenantUserMembership.merchant_id == merchant_id,
        TenantUserMembership.status == "active",
    ))
    if membership is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    merchant = db.get(Merchant, merchant_id)
    contract = db.scalar(select(TenantMerchantContract).where(
        TenantMerchantContract.tenant_merchant_id == merchant_id,
        TenantMerchantContract.status == "approved",
        TenantMerchantContract.kyc_status == "verified",
    ))
    if not merchant or merchant.status != "active" or not contract:
        raise HTTPException(status_code=403, detail="Tenant portal access is unavailable")
    return merchant


@router.get("/merchants")
def my_tenants(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    rows = db.execute(
        select(TenantUserMembership, Merchant, TenantMerchantContract)
        .join(Merchant, Merchant.id == TenantUserMembership.merchant_id)
        .join(TenantMerchantContract, TenantMerchantContract.tenant_merchant_id == Merchant.id)
        .where(
            TenantUserMembership.user_id == user.id,
            TenantUserMembership.status == "active",
            Merchant.status == "active",
            TenantMerchantContract.status == "approved",
            TenantMerchantContract.kyc_status == "verified",
        ).order_by(Merchant.name)
    ).all()
    return [{
        "merchant_id": merchant.id, "merchant_name": merchant.name,
        "role": membership.role, "custody_mode": contract.custody_mode,
    } for membership, merchant, contract in rows]


@router.get("/merchants/{merchant_id}/overview")
def merchant_overview(
    merchant_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    merchant = _allowed_tenant(db, user, merchant_id)
    contract = db.scalar(select(TenantMerchantContract).where(
        TenantMerchantContract.tenant_merchant_id == merchant_id,
    ))
    shortcodes = db.scalars(select(TenantProviderAccount).where(
        TenantProviderAccount.merchant_id == merchant_id,
    ).order_by(TenantProviderAccount.created_at.desc())).all()
    agreement = db.scalar(select(MerchantCommercialAgreement).where(
        MerchantCommercialAgreement.merchant_id == merchant_id,
        MerchantCommercialAgreement.status == "approved",
    ).order_by(MerchantCommercialAgreement.version.desc()))
    return {
        "merchant": {"id": merchant.id, "name": merchant.name, "slug": merchant.slug},
        "contract": {
            "status": contract.status,
            "kyc_status": contract.kyc_status,
            "custody_mode": contract.custody_mode,
        },
        "shortcodes": [{
            "id": row.id, "provider": row.provider,
            "environment": row.environment, "shortcode": row.shortcode,
            "ownership_status": row.ownership_status, "enabled": row.enabled,
        } for row in shortcodes],
        "agreement": None if agreement is None else {
            "version": agreement.version, "currency": agreement.currency,
            "inbound_fixed_fee": str(agreement.inbound_fixed_fee),
            "inbound_percentage_fee": str(agreement.inbound_percentage_fee),
            "outbound_fixed_fee": str(agreement.outbound_fixed_fee),
            "outbound_percentage_fee": str(agreement.outbound_percentage_fee),
            "provider_cost_payer": agreement.provider_cost_payer,
        },
        "payments_enabled_by_tenant_portal": False,
        "shared_custody_enabled": False,
    }


@admin_router.post("/memberships", status_code=201)
def grant_tenant_access(
    payload: TenantMembershipGrant,
    db: Session = Depends(get_db),
    admin: User = Depends(_network_admin),
):
    user = db.get(User, payload.user_id)
    merchant = db.get(Merchant, payload.merchant_id)
    contract = db.scalar(select(TenantMerchantContract).where(
        TenantMerchantContract.tenant_merchant_id == payload.merchant_id,
        TenantMerchantContract.status == "approved",
        TenantMerchantContract.kyc_status == "verified",
    ))
    if not user or not user.is_active or not merchant or merchant.status != "active" or not contract:
        raise HTTPException(status_code=409, detail="Active user and approved tenant required")
    row = TenantUserMembership(
        user_id=user.id, merchant_id=merchant.id, role=payload.role,
        status="active",
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Membership already exists") from None
    write_audit(
        db, actor_type="user", actor_id=admin.id,
        action="tenant_user_membership.granted",
        resource_type="tenant_user_membership", resource_id=row.id,
        merchant_id=merchant.id,
        metadata={"user_id": user.id, "role": row.role},
    )
    db.commit()
    return {
        "id": row.id, "user_id": user.id, "merchant_id": merchant.id,
        "role": row.role, "status": row.status,
    }


@admin_router.post("/memberships/{membership_id}/suspend")
def suspend_tenant_access(
    membership_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(_network_admin),
):
    row = db.scalar(select(TenantUserMembership).where(
        TenantUserMembership.id == membership_id,
    ).with_for_update())
    if row is None:
        raise HTTPException(status_code=404, detail="Membership not found")
    if row.status != "active":
        raise HTTPException(status_code=409, detail="Membership is not active")
    row.status = "suspended"
    write_audit(
        db, actor_type="user", actor_id=admin.id,
        action="tenant_user_membership.suspended",
        resource_type="tenant_user_membership", resource_id=row.id,
        merchant_id=row.merchant_id,
        metadata={"user_id": row.user_id},
    )
    db.commit()
    return {"id": row.id, "status": row.status}
