"""Administrator-only read-only status for LoanHub's Batlokoa master integration.

This endpoint does not issue credentials, authorize payments or share custody.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import (
    ApiKey, Application, GatewayProviderConfiguration, Merchant,
    PlatformMerchantSettings, User,
)
from database.session import get_db
from routers.merchant_network_admin import _network_admin

router = APIRouter(prefix="/admin/merchant-network", tags=["Merchant Network Administration"])

LOANHUB_COMPANY_ID = "4236a21f-5164-48aa-90f3-a35eccd23ae2"
MASTER_MERCHANT_ID = "3cc13734-5cd3-4ab4-9e4b-d378b715fa3f"
PROVIDER_CONFIGURATION_ID = "78e8842f-2f7b-4fd7-a113-7c6ca8798c51"
EXPECTED_SHORTCODE = "38542"
APPLICATION_NAME = "LoanHub - Batlokoa Financial Services"


def binding_status(
    master: PlatformMerchantSettings | None,
    merchant: Merchant | None,
    gateway: GatewayProviderConfiguration | None,
    applications: list[Application],
    key_count: int,
) -> dict:
    if (master is None or not master.active or master.merchant_id != MASTER_MERCHANT_ID):
        raise ValueError("Master merchant identity is not registered")
    if (merchant is None or merchant.id != MASTER_MERCHANT_ID or merchant.status != "active"):
        raise ValueError("Expected IthutePay master merchant not found")
    if (gateway is None or gateway.id != PROVIDER_CONFIGURATION_ID
            or gateway.provider != "mpesa" or gateway.environment != "production"
            or gateway.mode != "live" or gateway.active is not True
            or gateway.enabled is not True
            or str(gateway.service_provider_code or "") != EXPECTED_SHORTCODE):
        raise ValueError("M-PESA production provider identity mismatch")
    if master.shared_custody_enabled:
        raise ValueError("Shared custody needs a separate authorization review")
    if len(applications) != 1:
        raise ValueError("Expected exactly one dedicated LoanHub application")
    app = applications[0]
    if (app.name != APPLICATION_NAME or app.merchant_id != MASTER_MERCHANT_ID
            or app.environment != "test" or app.status != "inactive"):
        raise ValueError("LoanHub application binding is not in the approved inactive state")
    if key_count:
        raise ValueError("LoanHub application has credentials; manual security review required")
    return {
        "loanhub_company_id": LOANHUB_COMPANY_ID,
        "master_merchant_id": MASTER_MERCHANT_ID,
        "application_id": app.id,
        "application_status": "inactive",
        "mpesa_shortcode": EXPECTED_SHORTCODE,
        "provider_configuration_id": PROVIDER_CONFIGURATION_ID,
        "integration_status": "pending_authorization",
        "payment_routing_enabled": False,
        "shared_custody_enabled": False,
        "ithutepay_fee_policy": "requested_zero_not_enforced",
    }


@router.get("/loanhub-batlokoa-binding")
def read_loanhub_binding(
    db: Session = Depends(get_db),
    _: User = Depends(_network_admin),
):
    master = db.scalar(select(PlatformMerchantSettings).where(
        PlatformMerchantSettings.active.is_(True)
    ))
    merchant = db.get(Merchant, MASTER_MERCHANT_ID)
    gateway = db.get(GatewayProviderConfiguration, PROVIDER_CONFIGURATION_ID)
    apps = db.scalars(select(Application).where(
        Application.name == APPLICATION_NAME
    )).all()
    key_count = 0
    if len(apps) == 1:
        key_count = len(db.scalars(select(ApiKey.id).where(
            ApiKey.application_id == apps[0].id
        )).all())
    try:
        return binding_status(master, merchant, gateway, apps, key_count)
    except ValueError as exc:
        # This is an admin-only read, and intentionally fails closed.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
