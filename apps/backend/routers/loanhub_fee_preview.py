"""Administrator-only non-posting fee preview for the Batlokoa LoanHub app.

No merchant key is issued and no payment, payout, fee posting, settlement or
provider request is initiated by this endpoint.
"""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import (
    ApiKey, Application, GatewayProviderConfiguration, Merchant,
    PlatformMerchantSettings, User,
)
from database.session import get_db
from routers.loanhub_master_binding import (
    APPLICATION_NAME, MASTER_MERCHANT_ID, PROVIDER_CONFIGURATION_ID,
    binding_status,
)
from routers.merchant_network_admin import _network_admin
from services.loanhub_batlokoa_fee_policy import quote_batlokoa_platform_fee

router = APIRouter(
    prefix="/admin/merchant-network",
    tags=["Merchant Network Administration"],
)


class LoanHubFeePreviewInput(BaseModel):
    amount: Decimal = Field(gt=0, decimal_places=2, max_digits=18)
    currency: str = Field(default="LSL", pattern="^LSL$")
    operation: str = Field(pattern="^(collection|payout)$")


def build_fee_preview(
    *,
    master: PlatformMerchantSettings | None,
    merchant: Merchant | None,
    gateway: GatewayProviderConfiguration | None,
    applications: list[Application],
    api_key_count: int,
    payload: LoanHubFeePreviewInput,
) -> dict:
    """Use only server-loaded DB identities; never accept a company/merchant ID from the request."""
    state = binding_status(master, merchant, gateway, applications, api_key_count)
    app = applications[0]
    quote = quote_batlokoa_platform_fee(
        trusted_company_id=state["loanhub_company_id"],
        merchant_id=app.merchant_id,
        application_id=app.id,
        application_name=app.name,
        application_environment=app.environment,
        application_status=app.status,
        operation=payload.operation,
        currency=payload.currency,
        amount=payload.amount,
    )
    return {
        "loanhub_company_id": quote.company_id,
        "master_merchant_id": quote.master_merchant_id,
        "application_id": quote.application_id,
        "mpesa_shortcode": state["mpesa_shortcode"],
        "operation": quote.operation,
        "amount": str(quote.amount),
        "currency": quote.currency,
        "ithutepay_platform_fixed_fee": str(quote.platform_fixed_fee),
        "ithutepay_platform_percentage_fee": str(quote.platform_percentage_fee),
        "ithutepay_platform_total_fee": str(quote.platform_total_fee),
        "provider_charges_included": quote.provider_charges_included,
        "financial_posting_enabled": quote.financial_posting_enabled,
        "application_status": state["application_status"],
        "integration_status": state["integration_status"],
    }


@router.post("/loanhub-batlokoa/fee-preview")
def preview_loanhub_batlokoa_fee(
    payload: LoanHubFeePreviewInput,
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
        return build_fee_preview(
            master=master, merchant=merchant, gateway=gateway,
            applications=apps, api_key_count=key_count, payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
