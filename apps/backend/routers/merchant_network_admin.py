"""Platform-controlled master merchant onboarding and commercial agreements.

No money-moving routes use these records yet. Shared custody is blocked.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.access_control import get_current_active_user
from database.models import (
    Merchant, MerchantCommercialAgreement, PlatformMerchantSettings,
    TenantMerchantContract, TenantProviderAccount, User,
)
from database.session import get_db
from services.audit import write_audit
from services.commercial_pricing import CommercialTerms, fee_quote

router = APIRouter(prefix="/admin/merchant-network", tags=["Merchant Network Administration"])


def _network_admin(user: User = Depends(get_current_active_user)) -> User:
    # Commercial approval and merchant hierarchy must not be available to
    # operations, finance, developer or support roles.
    if str(user.role) not in {"platform_super_admin", "platform_admin"}:
        raise HTTPException(status_code=403, detail="Merchant-network administrator required")
    return user


class MasterRegistration(BaseModel):
    merchant_id: str = Field(min_length=36, max_length=36)


class TenantEnrollment(BaseModel):
    merchant_id: str = Field(min_length=36, max_length=36)
    custody_mode: str = Field(default="own_shortcode", pattern="^(own_shortcode|master_shortcode)$")


class TenantReview(BaseModel):
    approve: bool
    kyc_verified: bool = False
    evidence_reference: str = Field(min_length=8, max_length=180)


class AgreementProposal(BaseModel):
    version: int = Field(ge=1)
    currency: str = Field(default="LSL", pattern="^LSL$")
    inbound_fixed_fee: Decimal = Field(default=Decimal("0.00"), ge=0)
    inbound_percentage_fee: Decimal = Field(default=Decimal("0.00"), ge=0, le=100)
    outbound_fixed_fee: Decimal = Field(default=Decimal("0.00"), ge=0)
    outbound_percentage_fee: Decimal = Field(default=Decimal("0.00"), ge=0, le=100)
    provider_cost_payer: str = Field(default="tenant", pattern="^(tenant|ithute)$")


def _master(db: Session) -> PlatformMerchantSettings:
    row = db.scalar(select(PlatformMerchantSettings).where(
        PlatformMerchantSettings.active.is_(True),
    ))
    if row is None:
        raise HTTPException(status_code=409, detail="Ithute master merchant is not configured")
    return row


def _tenant(db: Session, merchant_id: str) -> TenantMerchantContract:
    row = db.scalar(select(TenantMerchantContract).where(
        TenantMerchantContract.tenant_merchant_id == merchant_id,
    ).with_for_update())
    if row is None:
        raise HTTPException(status_code=404, detail="Tenant contract not found")
    return row


def _contract_data(contract: TenantMerchantContract) -> dict:
    return {
        "id": contract.id,
        "master_merchant_id": contract.master_merchant_id,
        "tenant_merchant_id": contract.tenant_merchant_id,
        "custody_mode": contract.custody_mode,
        "status": contract.status,
        "kyc_status": contract.kyc_status,
    }


@router.post("/master", status_code=201)
def register_master(
    payload: MasterRegistration,
    db: Session = Depends(get_db), user: User = Depends(_network_admin),
):
    # Bootstrap is deliberately one-shot. Do not let an API rotate the platform
    # master without a formal migration/approval process.
    if db.scalar(select(PlatformMerchantSettings.id)):
        raise HTTPException(status_code=409, detail="Master merchant already registered")
    merchant = db.get(Merchant, payload.merchant_id)
    if not merchant or merchant.status != "active":
        raise HTTPException(status_code=404, detail="Active master merchant not found")
    row = PlatformMerchantSettings(
        merchant_id=merchant.id, active=True, shared_custody_enabled=False,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Master merchant already registered") from None
    write_audit(
        db, actor_type="user", actor_id=user.id, action="master_merchant.registered",
        resource_type="platform_merchant_settings", resource_id=row.id,
        merchant_id=merchant.id,
    )
    db.commit()
    return {"merchant_id": merchant.id, "active": True, "shared_custody_enabled": False}


@router.get("/master")
def get_master(
    db: Session = Depends(get_db), _: User = Depends(_network_admin),
):
    row = _master(db)
    return {
        "merchant_id": row.merchant_id,
        "active": row.active,
        "shared_custody_enabled": row.shared_custody_enabled,
    }


@router.post("/tenants", status_code=201)
def enroll_tenant(
    payload: TenantEnrollment,
    db: Session = Depends(get_db), user: User = Depends(_network_admin),
):
    master = _master(db)
    merchant = db.get(Merchant, payload.merchant_id)
    if not merchant or merchant.status != "active":
        raise HTTPException(status_code=404, detail="Active tenant merchant not found")
    if merchant.id == master.merchant_id:
        raise HTTPException(status_code=409, detail="Master cannot enroll itself")
    if db.scalar(select(TenantMerchantContract.id).where(
        TenantMerchantContract.tenant_merchant_id == merchant.id,
    )):
        raise HTTPException(status_code=409, detail="Tenant already enrolled")
    # Master-shortcode tenancy can be requested but NEVER approved here.
    row = TenantMerchantContract(
        master_merchant_id=master.merchant_id,
        tenant_merchant_id=merchant.id,
        custody_mode=payload.custody_mode,
        status="pending", kyc_status="pending", requested_by=str(user.id),
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Tenant already enrolled") from None
    write_audit(
        db, actor_type="user", actor_id=user.id, action="tenant_merchant.enrolled",
        resource_type="tenant_merchant_contract", resource_id=row.id,
        merchant_id=merchant.id, metadata={"custody_mode": row.custody_mode},
    )
    db.commit()
    return _contract_data(row)


@router.get("/tenants")
def list_tenants(
    db: Session = Depends(get_db), _: User = Depends(_network_admin),
):
    master = _master(db)
    rows = db.scalars(select(TenantMerchantContract).where(
        TenantMerchantContract.master_merchant_id == master.merchant_id,
    ).order_by(TenantMerchantContract.created_at.desc())).all()
    return [_contract_data(row) for row in rows]


@router.post("/tenants/{merchant_id}/review")
def review_tenant(
    merchant_id: str, payload: TenantReview,
    db: Session = Depends(get_db), user: User = Depends(_network_admin),
):
    row = _tenant(db, merchant_id)
    master = _master(db)
    if row.master_merchant_id != master.merchant_id or row.status != "pending":
        raise HTTPException(status_code=409, detail="Tenant is not pending review")
    if payload.approve:
        if row.custody_mode != "own_shortcode":
            raise HTTPException(
                status_code=409,
                detail="Master-shortcode custody requires separate provider and regulatory authorization",
            )
        if not payload.kyc_verified:
            raise HTTPException(status_code=409, detail="KYC verification required")
        if row.requested_by == str(user.id):
            raise HTTPException(status_code=409, detail="Different approver required")
        row.status, row.kyc_status = "approved", "verified"
        row.approved_by = str(user.id)
    else:
        row.status, row.kyc_status = "rejected", "rejected"
    write_audit(
        db, actor_type="user", actor_id=user.id, action="tenant_merchant.reviewed",
        resource_type="tenant_merchant_contract", resource_id=row.id,
        merchant_id=row.tenant_merchant_id,
        metadata={"status": row.status, "evidence_reference": payload.evidence_reference},
    )
    db.commit()
    return _contract_data(row)


@router.post("/tenants/{merchant_id}/suspend")
def suspend_tenant(
    merchant_id: str,
    db: Session = Depends(get_db), user: User = Depends(_network_admin),
):
    row = _tenant(db, merchant_id)
    if row.status != "approved":
        raise HTTPException(status_code=409, detail="Only approved tenants may be suspended")
    row.status = "suspended"
    # These flags are not yet live routing gates; future payment routing
    # must check contract status on EVERY operation.
    db.execute(
        TenantProviderAccount.__table__.update()
        .where(TenantProviderAccount.merchant_id == merchant_id)
        .values(enabled=False)
    )
    write_audit(
        db, actor_type="user", actor_id=user.id, action="tenant_merchant.suspended",
        resource_type="tenant_merchant_contract", resource_id=row.id,
        merchant_id=merchant_id,
    )
    db.commit()
    return _contract_data(row)


@router.post("/tenants/{merchant_id}/agreements", status_code=201)
def propose_agreement(
    merchant_id: str, payload: AgreementProposal,
    db: Session = Depends(get_db), user: User = Depends(_network_admin),
):
    row = _tenant(db, merchant_id)
    if row.status not in {"pending", "approved"}:
        raise HTTPException(status_code=409, detail="Tenant is not eligible")
    agreement = MerchantCommercialAgreement(
        merchant_id=merchant_id, version=payload.version, currency=payload.currency,
        inbound_fixed_fee=payload.inbound_fixed_fee,
        inbound_percentage_fee=payload.inbound_percentage_fee,
        outbound_fixed_fee=payload.outbound_fixed_fee,
        outbound_percentage_fee=payload.outbound_percentage_fee,
        provider_cost_payer=payload.provider_cost_payer,
        proposed_by=str(user.id), status="draft",
    )
    db.add(agreement)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Agreement version already exists") from None
    write_audit(
        db, actor_type="user", actor_id=user.id, action="merchant_agreement.proposed",
        resource_type="merchant_commercial_agreement", resource_id=agreement.id,
        merchant_id=merchant_id, metadata={"version": agreement.version},
    )
    db.commit()
    return {"id": agreement.id, "version": agreement.version, "status": agreement.status}


@router.get("/agreements")
def list_agreements(
    db: Session = Depends(get_db), _: User = Depends(_network_admin),
):
    master = _master(db)
    tenant_ids = select(TenantMerchantContract.tenant_merchant_id).where(
        TenantMerchantContract.master_merchant_id == master.merchant_id,
    )
    rows = db.scalars(select(MerchantCommercialAgreement).where(
        MerchantCommercialAgreement.merchant_id.in_(tenant_ids),
    ).order_by(
        MerchantCommercialAgreement.created_at.desc(),
    )).all()
    return [{
        "id": row.id, "merchant_id": row.merchant_id,
        "version": row.version, "status": row.status, "currency": row.currency,
        "inbound_fixed_fee": str(row.inbound_fixed_fee),
        "inbound_percentage_fee": str(row.inbound_percentage_fee),
        "outbound_fixed_fee": str(row.outbound_fixed_fee),
        "outbound_percentage_fee": str(row.outbound_percentage_fee),
        "provider_cost_payer": row.provider_cost_payer,
        "proposed_by": row.proposed_by,
        "approved_by": row.approved_by,
    } for row in rows]


@router.post("/agreements/{agreement_id}/approve")
def approve_agreement(
    agreement_id: str,
    db: Session = Depends(get_db), user: User = Depends(_network_admin),
):
    agreement = db.scalar(select(MerchantCommercialAgreement).where(
        MerchantCommercialAgreement.id == agreement_id,
    ).with_for_update())
    if agreement is None:
        raise HTTPException(status_code=404, detail="Agreement not found")
    tenant = _tenant(db, agreement.merchant_id)
    if tenant.status != "approved" or tenant.custody_mode != "own_shortcode":
        raise HTTPException(status_code=409, detail="Only approved own-shortcode tenants are eligible")
    if agreement.status != "draft":
        raise HTTPException(status_code=409, detail="Agreement is not a draft")
    if agreement.proposed_by == str(user.id):
        raise HTTPException(status_code=409, detail="Different approver required")
    if db.scalar(select(MerchantCommercialAgreement.id).where(
        MerchantCommercialAgreement.merchant_id == agreement.merchant_id,
        MerchantCommercialAgreement.status == "approved",
    )):
        raise HTTPException(status_code=409, detail="Retire current agreement before approval")
    agreement.status = "approved"
    agreement.approved_by = str(user.id)
    agreement.approved_at = datetime.now(timezone.utc)
    agreement.effective_at = agreement.approved_at
    write_audit(
        db, actor_type="user", actor_id=user.id, action="merchant_agreement.approved",
        resource_type="merchant_commercial_agreement", resource_id=agreement.id,
        merchant_id=agreement.merchant_id,
        metadata={"version": agreement.version},
    )
    db.commit()
    return {"id": agreement.id, "version": agreement.version, "status": agreement.status}


@router.get("/agreements/{agreement_id}/quote")
def quote_approved_agreement(
    agreement_id: str,
    amount: Decimal = Query(gt=0, le=100000000, decimal_places=2),
    direction: str = Query(pattern="^(inbound|outbound)$"),
    db: Session = Depends(get_db),
    _: User = Depends(_network_admin),
):
    """Read-only commercial quote; never creates a payment or posts a fee.

    Restricted to platform network administrators because tenant commercial
    terms are private and must not be readable across unrelated tenants.
    """
    agreement = db.get(MerchantCommercialAgreement, agreement_id)
    if agreement is None:
        raise HTTPException(status_code=404, detail="Agreement not found")

    master = _master(db)
    contract = db.scalar(select(TenantMerchantContract).where(
        TenantMerchantContract.tenant_merchant_id == agreement.merchant_id,
        TenantMerchantContract.master_merchant_id == master.merchant_id,
    ))
    if (
        contract is None or contract.status != "approved"
        or contract.kyc_status != "verified"
        or contract.custody_mode != "own_shortcode"
        or agreement.status != "approved"
    ):
        raise HTTPException(status_code=409, detail="Approved own-shortcode contract and agreement required")

    terms = CommercialTerms(
        currency=agreement.currency,
        inbound_fixed_fee=agreement.inbound_fixed_fee,
        inbound_percentage_fee=agreement.inbound_percentage_fee,
        outbound_fixed_fee=agreement.outbound_fixed_fee,
        outbound_percentage_fee=agreement.outbound_percentage_fee,
        provider_cost_payer=agreement.provider_cost_payer,
    )
    try:
        quote = fee_quote(amount, direction, terms)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        **quote,
        "merchant_id": agreement.merchant_id,
        "agreement_id": agreement.id,
        "agreement_version": agreement.version,
        "quotation_only": True,
        "warning": "Commercial fees only; excludes provider costs, settlement rules and authorization. No funds move.",
    }


@router.get("/tenants/{merchant_id}/readiness")
def tenant_commercial_readiness(
    merchant_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(_network_admin),
):
    """Report onboarding evidence without asserting payment-rail activation."""
    master = _master(db)
    contract = db.scalar(select(TenantMerchantContract).where(
        TenantMerchantContract.tenant_merchant_id == merchant_id,
        TenantMerchantContract.master_merchant_id == master.merchant_id,
    ))
    if contract is None:
        raise HTTPException(status_code=404, detail="Tenant contract not found")

    approved_agreement = db.scalar(select(MerchantCommercialAgreement).where(
        MerchantCommercialAgreement.merchant_id == merchant_id,
        MerchantCommercialAgreement.status == "approved",
    ).order_by(MerchantCommercialAgreement.version.desc()))

    provider_accounts = db.scalars(select(TenantProviderAccount).where(
        TenantProviderAccount.merchant_id == merchant_id,
    )).all()
    verified_own_shortcode = any(
        account.ownership_status == "verified"
        and account.verified_at is not None
        and account.provider == "mpesa"
        and account.environment == "production"
        for account in provider_accounts
    )
    checks = {
        "contract_approved": contract.status == "approved",
        "kyc_verified": contract.kyc_status == "verified",
        "own_shortcode": contract.custody_mode == "own_shortcode",
        "commercial_agreement_approved": approved_agreement is not None,
        "production_shortcode_verified": verified_own_shortcode,
    }
    return {
        "merchant_id": merchant_id,
        "checks": checks,
        "missing": [key for key, complete in checks.items() if not complete],
        "onboarding_evidence_complete": all(checks.values()),
        # This endpoint MUST NOT imply payment execution is live. Enforcement
        # at each money-moving route and provider approval remain separate.
        "payment_execution_enabled": False,
        "settlement_enabled": False,
        "master_short_code_custody_enabled": False,
        "warning": "Onboarding evidence is not permission to process funds.",
    }
