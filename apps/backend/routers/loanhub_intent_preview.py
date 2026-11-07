"""Admin-only, non-posting collection-intent preview for LoanHub/Batlokoa.

This endpoint does not create payment intents, reserve idempotency keys,
issue API keys, call M-PESA, or authorize any financial execution.
"""
from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
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
from services.loanhub_batlokoa_intent_preview import (
    preview_batlokoa_collection_intent,
)

router = APIRouter(
    prefix="/admin/merchant-network",
    tags=["Merchant Network Administration"],
)


class CollectionIntentPreviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Decimal = Field(gt=0, decimal_places=2, max_digits=18)
    currency: str = Field(default="LSL", pattern="^LSL$")
    source_reference: str = Field(min_length=8, max_length=128)
    idempotency_key: str = Field(min_length=16, max_length=128)


def build_collection_intent_preview(
    *,
    master: PlatformMerchantSettings | None,
    merchant: Merchant | None,
    gateway: GatewayProviderConfiguration | None,
    applications: list[Application],
    api_key_count: int,
    payload: CollectionIntentPreviewInput,
) -> dict:
    """Resolve all merchant, company and app identities from database records."""
    state = binding_status(master, merchant, gateway, applications, api_key_count)
    application = applications[0]
    quote = preview_batlokoa_collection_intent(
        trusted_company_id=state["loanhub_company_id"],
        merchant_id=application.merchant_id,
        application_id=application.id,
        application_name=application.name,
        application_environment=application.environment,
        application_status=application.status,
        source_reference=payload.source_reference,
        idempotency_key=payload.idempotency_key,
        amount=payload.amount,
        currency=payload.currency,
    )
    return {
        **asdict(quote),
        "mpesa_shortcode": state["mpesa_shortcode"],
        "application_status": state["application_status"],
        "integration_status": state["integration_status"],
    }


@router.post("/loanhub-batlokoa/collection-intent-preview")
def preview_batlokoa_collection(
    payload: CollectionIntentPreviewInput,
    db: Session = Depends(get_db),
    _: User = Depends(_network_admin),
):
    master = db.scalar(select(PlatformMerchantSettings).where(
        PlatformMerchantSettings.active.is_(True),
    ))
    merchant = db.get(Merchant, MASTER_MERCHANT_ID)
    gateway = db.get(GatewayProviderConfiguration, PROVIDER_CONFIGURATION_ID)
    applications = db.scalars(select(Application).where(
        Application.name == APPLICATION_NAME,
    )).all()
    key_count = 0
    if len(applications) == 1:
        key_count = len(db.scalars(select(ApiKey.id).where(
            ApiKey.application_id == applications[0].id,
        )).all())
    try:
        return build_collection_intent_preview(
            master=master,
            merchant=merchant,
            gateway=gateway,
            applications=applications,
            api_key_count=key_count,
            payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
